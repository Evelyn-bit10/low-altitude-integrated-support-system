# -*- coding: utf-8 -*-
"""场景对比：同一批仿真数据上，把"规则"和"PPO 策略"各跑一遍，用**真值**打分。

和影子模式的区别：
    影子模式跑在真实/仿真流上，只能看"两边是否一致"（没有真值）；
    这里跑在带真值的仿真场景上，能直接算出**误配 / 漏配 / 碎片数**，
    所以更适合回答"到底谁更对"。

只依赖标准库 + 项目内模块（不依赖 numpy / paddle）：
    推理用 app/services/shadow.py 里的纯 Python 前向。
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Any, Dict, List

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EXP = os.path.join(_BACKEND, "experiments")
for _p in (os.path.join(_EXP, "rl_dedup"), os.path.join(_EXP, "dedup_ml")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from env import AssociationEnv                       # noqa: E402
from app.services.shadow import ShadowPolicy          # noqa: E402

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_policy = None

SCENARIOS = {
    "sparse":     {"label": "稀疏空域", "level": "noid", "frames": 30, "seed": 71},
    "dense":      {"label": "密集空域", "level": "noid", "frames": 30, "seed": 72},
    "hard_dense": {"label": "困难密集", "level": "hard", "frames": 30, "seed": 73},
    "swarm":      {"label": "蜂群 40×40m", "level": "noid", "frames": 30, "seed": 74},
    "orbit":      {"label": "盘旋机动", "level": "noid", "frames": 30, "seed": 75},
}


def _get_policy() -> ShadowPolicy:
    global _policy
    if _policy is None:
        _policy = ShadowPolicy(
            os.path.join(_EXP, "rl_dedup", "policy_weights.json"),
            os.path.join(_EXP, "rl_dedup", "rl_params.json"),
        )
    return _policy


def _rollout(scn: str, level: str, frames: int, seed: int, use_policy: bool) -> dict:
    """跑一局，返回带真值的指标。"""
    env = AssociationEnv(scn, level=level, frames=frames, seed=seed)
    if not use_policy:
        r = env.run_policy(lambda f, rule: 1.0 if rule > 0 else 0.0)
        return {
            "reward": round(r["reward"], 1), "correct": r["true"],
            "wrong": r["wrong"], "miss": r["miss"], "created": r["created"],
            "frags": round(r["avg_frags"], 2), "split": round(r["split_ratio"], 3),
        }

    pol = _get_policy()
    st = env.reset()
    tot = {"reward": 0.0, "true": 0, "wrong": 0, "miss": 0, "created": 0}
    while not st.get("done"):
        if not st["feats"]:
            st, _, done, _ = env.step([])
            continue
        probs = pol.score(st["feats"])
        probs = [p * (1.0 - m) for p, m in zip(probs, st["masked"])]   # 硬约束
        actions = [1 if p >= pol.threshold else 0 for p in probs]
        st, r, done, info = env.step_actions(probs, actions)
        tot["reward"] += r
        for k in ("true", "wrong", "miss", "created"):
            tot[k] += info.get(k, 0)
    frag = env.truth_tracks
    tot["frags"] = round(sum(len(v) for v in frag.values()) / max(1, len(frag)), 2)
    tot["split"] = round(sum(1 for v in frag.values() if len(v) > 1) / max(1, len(frag)), 3)
    tot["reward"] = round(tot["reward"], 1)
    tot["correct"] = tot.pop("true")
    return tot


def compare(scenario: str = "swarm", frames: int | None = None) -> dict:
    """跑一个场景：规则 vs 策略，返回对比结果（带缓存）。"""
    cfg = SCENARIOS.get(scenario)
    if cfg is None:
        raise ValueError("未知场景: %s" % scenario)
    n = int(frames or cfg["frames"])
    key = "%s:%d" % (scenario, n)
    with _lock:
        if key in _cache:
            return _cache[key]
        rule = _rollout(scenario, cfg["level"], n, cfg["seed"], use_policy=False)
        pol = _rollout(scenario, cfg["level"], n, cfg["seed"], use_policy=True)
        out = {
            "scenario": scenario, "label": cfg["label"], "frames": n,
            "threshold": _get_policy().threshold,
            "rule": rule, "policy": pol,
            "delta": {
                "reward": round(pol["reward"] - rule["reward"], 1),
                "wrong": pol["wrong"] - rule["wrong"],
                "miss": pol["miss"] - rule["miss"],
                "frags": round(pol["frags"] - rule["frags"], 2),
            },
        }
        _cache[key] = out
        return out


def compare_all(frames: int | None = None) -> List[dict]:
    return [compare(s, frames) for s in SCENARIOS]
