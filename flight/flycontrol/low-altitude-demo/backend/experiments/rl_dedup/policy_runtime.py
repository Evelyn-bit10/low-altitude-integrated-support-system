# -*- coding: utf-8 -*-
"""策略运行时（纯 numpy，不依赖 Paddle）。

用法::

    from policy_runtime import PolicyRuntime
    pol = PolicyRuntime("experiments/rl_dedup/policy_weights.json")
    scores = pol.score(features)      # features: [[...18 维...], ...] -> [0,1]

特征顺序与 ppo_meta.json 的 features 一致。
"""
from __future__ import annotations

import json
import numpy as np


class PolicyRuntime:
    def __init__(self, path: str):
        cfg = json.load(open(path, encoding="utf-8"))
        self.features = cfg["features"]
        self.mean = np.asarray(cfg["mean"], dtype=np.float64)
        self.std = np.asarray(cfg["std"], dtype=np.float64)
        w = cfg["weights"]
        self.W0 = np.asarray(w["enc0_w"], dtype=np.float64)
        self.b0 = np.asarray(w["enc0_b"], dtype=np.float64)
        self.W2 = np.asarray(w["enc2_w"], dtype=np.float64)
        self.b2 = np.asarray(w["enc2_b"], dtype=np.float64)
        self.Wa = np.asarray(w["actor_w"], dtype=np.float64)
        self.ba = np.asarray(w["actor_b"], dtype=np.float64)

    def logits(self, feats) -> np.ndarray:
        x = (np.asarray(feats, dtype=np.float64) - self.mean) / np.maximum(self.std, 1e-6)
        h = np.tanh(x @ self.W0 + self.b0)
        h = np.tanh(h @ self.W2 + self.b2)
        return (h @ self.Wa + self.ba).reshape(-1)

    def score(self, feats) -> np.ndarray:
        """返回每条候选边的"同一架"概率。"""
        z = np.clip(self.logits(feats), -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-z))
