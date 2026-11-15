# -*- coding: utf-8 -*-
"""把飞桨训练的策略导出成纯 JSON 权重 + 纯 Python 推理（线上不依赖 Paddle）。

运行：
    python experiments/rl_dedup/export_policy.py
"""
from __future__ import annotations
import json, os, sys
import numpy as np
import paddle

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from train_ppo import EdgePolicy  # noqa: E402

import math


def forward_np(x, w):
    """与 EdgePolicy.forward 等价的纯 numpy 前向。

    注意：Paddle 的 Linear 权重形状是 [in, out]（与 PyTorch 的 [out, in] 相反），
    所以这里是 x @ W，不需要转置。
    """
    h = x @ w["enc0_w"] + w["enc0_b"]
    h = np.tanh(h)
    h = h @ w["enc2_w"] + w["enc2_b"]
    h = np.tanh(h)
    logits = (h @ w["actor_w"] + w["actor_b"]).reshape(-1)
    return logits


def main() -> int:
    meta = json.load(open(os.path.join(_HERE, "ppo_meta.json"), encoding="utf-8"))
    dim = len(meta["features"])
    policy = EdgePolicy(dim)
    sd = paddle.load(os.path.join(_HERE, "ppo_policy.pdparams"))
    policy.set_state_dict(sd)

    # 名字映射：state_dict 的 key 形如 enc.0.weight
    w = {
        "enc0_w": sd["enc.0.weight"].numpy().astype(np.float64),
        "enc0_b": sd["enc.0.bias"].numpy().astype(np.float64),
        "enc2_w": sd["enc.2.weight"].numpy().astype(np.float64),
        "enc2_b": sd["enc.2.bias"].numpy().astype(np.float64),
        "actor_w": sd["actor.weight"].numpy().astype(np.float64),
        "actor_b": sd["actor.bias"].numpy().astype(np.float64),
    }

    # 校验：随机特征上，numpy 与 paddle 输出一致
    x = np.random.randn(32, dim).astype(np.float32)
    logits_np = forward_np(x.astype(np.float64), w)
    with paddle.no_grad():
        logits_pd, _ = policy(paddle.to_tensor(x))
    diff = float(np.abs(logits_np - logits_pd.numpy()).max())
    print("导出校验：numpy vs paddle 最大误差 %.2e" % diff)
    assert diff < 1e-5, "导出结果与飞桨不一致"

    out = {
        "features": meta["features"],
        "mean": meta["mean"],
        "std": meta["std"],
        "weights": {k: v.tolist() for k, v in w.items()},
        "test": meta.get("test"), "rule": meta.get("rule"),
    }
    path = os.path.join(_HERE, "policy_weights.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("已导出: %s（%.0f KB）" % (path, os.path.getsize(path) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
