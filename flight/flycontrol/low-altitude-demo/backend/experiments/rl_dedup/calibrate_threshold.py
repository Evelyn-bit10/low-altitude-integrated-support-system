# -*- coding: utf-8 -*-
"""标定决策阈值，输出生产可用参数文件 rl_params.json。

为什么需要标定：
    策略输出的是"同一架"的概率，但**用哪个阈值去接受**是业务决策：
    阈值低 → 合并更激进（漏配少、误配多）；阈值高 → 保守。
    这里按"误配数不超过规则基线"的安全约束反解阈值，再在该约束下最大化奖励。

运行：
    python experiments/rl_dedup/calibrate_threshold.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from env import AssociationEnv          # noqa: E402
from policy_runtime import PolicyRuntime  # noqa: E402

VAL_CASES = [("sparse", "noid", 71), ("dense", "noid", 72),
             ("hard_dense", "hard", 73), ("swarm", "noid", 74)]
FRAMES = 40


def run_with_threshold(pol, cases, thr):
    """用指定阈值跑完所有验证场景，返回汇总指标。"""
    agg = {"reward": 0.0, "wrong": 0, "miss": 0, "true": 0, "frags": 0.0, "split": 0.0}
    n = len(cases)
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=seed)
        st = env.reset()
        while not st.get("done"):
            if len(st["feats"]) == 0:
                st, _, done, _ = env.step([])
                continue
            p = pol.score(st["feats"]) * (1.0 - np.array(st["masked"], dtype=np.float64))
            actions = (p >= thr).astype(np.int32)
            st, r, done, info = env.step_actions(list(p), list(actions))
            agg["reward"] += r
            for k in ("wrong", "miss", "true"):
                agg[k] += info.get(k, 0)
        frag = env.truth_tracks
        agg["frags"] += sum(len(v) for v in frag.values()) / max(1, len(frag))
        agg["split"] += sum(1 for v in frag.values() if len(v) > 1) / max(1, len(frag))
    for k in ("reward", "frags", "split"):
        agg[k] /= n
    return agg


def run_rule(cases):
    agg = {"reward": 0.0, "wrong": 0, "miss": 0, "true": 0, "frags": 0.0, "split": 0.0}
    n = len(cases)
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=seed)
        r = env.run_policy(lambda f, rule: 1.0 if rule > 0 else 0.0)
        agg["reward"] += r["reward"]
        for k in ("wrong", "miss", "true"):
            agg[k] += r[k]
        frag = env.truth_tracks
        agg["frags"] += sum(len(v) for v in frag.values()) / max(1, len(frag))
        agg["split"] += sum(1 for v in frag.values() if len(v) > 1) / max(1, len(frag))
    for k in ("reward", "frags", "split"):
        agg[k] /= n
    return agg


def main() -> int:
    pol = PolicyRuntime(os.path.join(_HERE, "policy_weights.json"))
    rule = run_rule(VAL_CASES)
    print("规则基线（验证集）：奖励 %.1f  错配 %.0f  漏配 %.0f  碎片 %.2f"
          % (rule["reward"], rule["wrong"], rule["miss"], rule["frags"]))

    print("\n阈值扫描")
    print("-" * 76)
    print("%-6s %10s %8s %8s %8s" % ("阈值", "奖励", "错配", "漏配", "碎片"))
    rows = []
    for thr in np.arange(0.30, 0.86, 0.05):
        m = run_with_threshold(pol, VAL_CASES, float(thr))
        rows.append((float(thr), m))
        print("%-6.2f %10.1f %8.0f %8.0f %8.2f"
              % (thr, m["reward"], m["wrong"], m["miss"], m["frags"]))

    # 约束：误配不超过规则；在此前提下奖励最高
    feasible = [(t, m) for t, m in rows if m["wrong"] <= max(1.0, rule["wrong"] * 1.0)]
    if feasible:
        best_thr, best = max(feasible, key=lambda x: x[1]["reward"])
        rule_desc = "误配 ≤ 规则基线"
    else:
        best_thr, best = max(rows, key=lambda x: x[1]["reward"])
        rule_desc = "无可行阈值，取奖励最优"
    print("\n选定阈值 %.2f（约束：%s）" % (best_thr, rule_desc))
    print("预期指标：奖励 %.1f  错配 %.0f  漏配 %.0f  碎片 %.2f  被拆 %.0f%%"
          % (best["reward"], best["wrong"], best["miss"], best["frags"], best["split"] * 100))

    # 与规则对比
    print("\n相对规则：奖励 %+.1f  错配 %+.0f  漏配 %+.0f  碎片 %+.2f"
          % (best["reward"] - rule["reward"], best["wrong"] - rule["wrong"],
             best["miss"] - rule["miss"], best["frags"] - rule["frags"]))

    out = {
        "policy_file": "policy_weights.json",
        "features": pol.features,
        "threshold": round(best_thr, 2),
        "decision_rule": "score >= threshold 即接受该边；同一来源对同一航迹只接受一次",
        "safety_rules": ["ua_id 冲突一票否决（masked）"],
        "calibrated_on": [list(c) for c in VAL_CASES],
        "expected": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in best.items()},
        "rule_baseline": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rule.items()},
    }
    path = os.path.join(_HERE, "rl_params.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n参数已保存: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
