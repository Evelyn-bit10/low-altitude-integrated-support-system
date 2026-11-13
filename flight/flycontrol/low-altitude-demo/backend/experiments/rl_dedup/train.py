# -*- coding: utf-8 -*-
"""用策略搜索（CEM / 交叉熵法）训练一个「关联策略」，与规则基线对比。

策略：score(e) = sigmoid(w · [features, 1])，17 个参数。
训练：CEM —— 采参数、跑整局、按累计奖励选精英、更新分布。
奖励：正确 +1 / 错配 −10 / 漏配 −1（与 env.py 一致，安全优先）。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python experiments\\rl_dedup\\train.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from env import AssociationEnv  # noqa: E402
import sim                      # noqa: E402

TRAIN = [("sparse", "noid", 1), ("dense", "noid", 2),
         ("hard_dense", "hard", 3), ("formation", "hard", 4),
         ("swarm", "noid", 5)]
TEST = [("sparse", "noid", 51), ("dense", "noid", 52),
        ("hard_dense", "hard", 53), ("swarm", "noid", 54)]
DIM = len(sim.FEATURE_NAMES) + 1        # +1 = bias


def policy_score(w, f):
    x = np.append(f, 1.0)
    z = float(np.dot(w, x))
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + np.exp(-z))


def rule_score(_f, rule):
    return 1.0 if rule > 0 else 0.0


def evaluate(w, cases, frames=40):
    out = []
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=frames, seed=seed)
        out.append(env.run_policy(lambda f, r: policy_score(w, f)))
    return aggregate(out)


def evaluate_rule(cases, frames=40):
    out = []
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=frames, seed=seed)
        out.append(env.run_policy(rule_score))
    return aggregate(out)


def aggregate(rows):
    n = max(1, len(rows))
    return {
        "reward": sum(r["reward"] for r in rows) / n,
        "wrong": sum(r["wrong"] for r in rows) / n,
        "miss": sum(r["miss"] for r in rows) / n,
        "true": sum(r["true"] for r in rows) / n,
        "frags": sum(r["avg_frags"] for r in rows) / n,
        "split": sum(r["split_ratio"] for r in rows) / n,
    }


def train(iterations=14, pop=14, elite=4, seed=0):
    rng = np.random.default_rng(seed)
    mu = np.zeros(DIM)
    sigma = np.ones(DIM) * 0.8
    best_w, best_r = mu.copy(), -1e18
    history = []

    for it in range(iterations):
        cands = [mu + sigma * rng.standard_normal(DIM) for _ in range(pop)]
        scored = []
        for w in cands:
            r = evaluate(w, TRAIN)["reward"]
            scored.append((r, w))
        scored.sort(key=lambda x: -x[0])
        elites = np.array([w for _, w in scored[:elite]])
        mu = 0.3 * mu + 0.7 * elites.mean(axis=0)
        sigma = 0.3 * sigma + 0.7 * elites.std(axis=0) + 1e-3
        top_r = scored[0][0]
        if top_r > best_r:
            best_r, best_w = top_r, scored[0][1].copy()
        history.append(top_r)
        print("  iter %2d  最佳奖励 %8.1f  精英均值 %8.1f  σ均值 %.3f"
              % (it + 1, top_r, sum(r for r, _ in scored[:elite]) / elite, sigma.mean()))

    return best_w, best_r, history


def main() -> int:
    print("=" * 84)
    print(" 强化学习（策略搜索）vs 规则基线")
    print(" 动作=每条候选边的匹配概率；奖励：正确+1 / 错配−10 / 漏配−1")
    print("=" * 84)

    base = evaluate_rule(TEST)
    print("\n规则基线（测试集）：奖励 %.1f  错配 %.0f  漏配 %.0f  碎片 %.2f  被拆 %.0f%%"
          % (base["reward"], base["wrong"], base["miss"], base["frags"], base["split"] * 100))

    print("\n训练（CEM 策略搜索）…")
    w, r, hist = train()

    pol = evaluate(w, TEST)
    print("\n训练后（测试集）：奖励 %.1f  错配 %.0f  漏配 %.0f  碎片 %.2f  被拆 %.0f%%"
          % (pol["reward"], pol["wrong"], pol["miss"], pol["frags"], pol["split"] * 100))

    print("\n对比")
    print("-" * 84)
    print("%-8s %10s %8s %8s %8s %8s" % ("方法", "累计奖励", "错配", "漏配", "碎片数", "被拆占比"))
    print("%-8s %10.1f %8.0f %8.0f %8.2f %7.0f%%"
          % ("规则", base["reward"], base["wrong"], base["miss"], base["frags"], base["split"] * 100))
    print("%-8s %10.1f %8.0f %8.0f %8.2f %7.0f%%"
          % ("策略", pol["reward"], pol["wrong"], pol["miss"], pol["frags"], pol["split"] * 100))

    # 学到的权重（转成可读）
    print("\n学到的策略权重（按 |权重| 排序）")
    names = list(sim.FEATURE_NAMES) + ["bias"]
    for i in np.argsort(-np.abs(w))[:8]:
        print("  %-16s %+7.3f" % (names[i], w[i]))

    out = os.path.join(_HERE, "rl_policy.json")
    json.dump({"weights": list(map(float, w)), "features": names,
               "train_reward": float(r)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n策略已保存: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
