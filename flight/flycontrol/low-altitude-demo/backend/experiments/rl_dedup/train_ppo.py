# -*- coding: utf-8 -*-
"""PPO（飞桨 / PaddlePaddle）训练航迹关联策略。

环境：experiments/rl_dedup/env.py
动作：每条候选边是否关联（二值）；用概率排序后贪心解码
奖励（逐边，便于信用分配）：正确 +1 ｜ 错配 −6 ｜ 漏配 −2

运行（用装好 paddle 的环境）：
    C:\\Users\\Lenovo\\rl-venv\\Scripts\\python.exe experiments\\rl_dedup\\train_ppo.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import paddle
import paddle.nn as nn
import paddle.nn.functional as F

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from env import AssociationEnv  # noqa: E402

paddle.set_device("cpu")
paddle.seed(0)
np.random.seed(0)

TRAIN_CASES = [("sparse", "noid", 1), ("dense", "noid", 2),
               ("hard_dense", "hard", 3), ("formation", "hard", 4),
               ("swarm", "noid", 5)]
TEST_CASES = [("sparse", "noid", 51), ("dense", "noid", 52),
              ("hard_dense", "hard", 53), ("swarm", "noid", 54)]
FRAMES = 40


class EdgePolicy(nn.Layer):
    def __init__(self, dim: int, hidden: int = 64):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(dim, hidden), nn.Tanh(),
                                 nn.Linear(hidden, hidden), nn.Tanh())
        self.actor = nn.Linear(hidden, 1)
        self.critic = nn.Sequential(nn.Linear(hidden, hidden), nn.Tanh(),
                                    nn.Linear(hidden, 1))

    def forward(self, x):
        h = self.enc(x)
        logits = self.actor(h).squeeze(-1)
        value = self.critic(h.mean(axis=0)).squeeze(-1)
        return logits, value


class Normalizer:
    def __init__(self, dim):
        self.mean = np.zeros(dim, dtype=np.float32)
        self.std = np.ones(dim, dtype=np.float32)
        self.n = 0

    def update(self, X):
        X = np.asarray(X, dtype=np.float32)
        if len(X) == 0:
            return
        n = len(X)
        self.n += n
        w = n / max(1, self.n)
        self.mean = (1 - w) * self.mean + w * X.mean(axis=0)
        self.std = (1 - w) * self.std + w * (X.std(axis=0) + 1e-6)

    def __call__(self, X):
        return (np.asarray(X, dtype=np.float32) - self.mean) / np.maximum(self.std, 1e-6)


def logp_vec(logits, actions):
    """每条边的对数概率。"""
    a = paddle.to_tensor(actions.astype("float32"))
    return a * F.log_sigmoid(logits) + (1.0 - a) * F.log_sigmoid(-logits)


def warm_start(policy, norm, cases, epochs=8, lr=1e-3, batch=512):
    """规则热启动：监督学习让策略先学会"像规则一样打分"。

    直接用 Paddle 优化器做 BCE，避免 PPO 从随机初始化滑向"一律不合并"。
    """
    X_all, y_all = [], []
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=seed)
        st = env.reset()
        while not st.get("done"):
            if len(st["feats"]) == 0:
                st, _, done, _ = env.step([])
                continue
            X_all.extend(st["feats"])
            y_all.extend([1.0 if ru > 0 else 0.0 for ru in st["rules"]])
            scores = [1.0 + ru if ru > 0 else 0.0 for ru in st["rules"]]
            st, _, done, _ = env.step(scores)
    if not X_all:
        return
    X = paddle.to_tensor(norm(X_all))
    y = paddle.to_tensor(np.array(y_all, dtype="float32"))
    opt = paddle.optimizer.Adam(learning_rate=lr, parameters=policy.parameters())
    pos = float(np.mean(y_all)) * 100
    print("  样本 %d 条（正样本 %.1f%%）" % (len(y_all), pos))
    for ep in range(epochs):
        perm = np.random.permutation(len(y_all))
        total = 0.0
        for s0 in range(0, len(perm), batch):
            idx = paddle.to_tensor(perm[s0:s0 + batch].astype("int64"))
            logits, _ = policy(paddle.gather(X, idx))
            loss = F.binary_cross_entropy_with_logits(logits, paddle.gather(y, idx))
            loss.backward()
            opt.step()
            opt.clear_grad()
            total += float(loss) * len(idx)
        print("    warm epoch %d  BCE %.4f" % (ep + 1, total / len(y_all)))


def collect(policy, norm, cases):
    batch, stats = [], {"reward": 0.0, "wrong": 0, "miss": 0, "true": 0}
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=seed)
        st = env.reset()
        while not st.get("done"):
            if len(st["feats"]) == 0:
                st, _, done, _ = env.step([])
                continue
            X = norm(st["feats"])
            mask = np.array(st["masked"], dtype=np.float32)
            with paddle.no_grad():
                logits, value = policy(paddle.to_tensor(X))
                p = F.sigmoid(logits).numpy()
            p = p * (1.0 - mask)
            a = (np.random.rand(len(p)) < p).astype(np.int32)
            with paddle.no_grad():
                lp = logp_vec(logits, a).numpy()

            st2, r, done, info = env.step_actions(list(p), list(a))
            er = np.array(info.get("edge_rewards", []), dtype=np.float32)
            if len(er) != len(a):
                er = np.zeros(len(a), dtype=np.float32)
            batch.append({"X": X, "a": a, "mask": mask, "p": p,
                          "logp": lp, "v": float(value), "er": er,
                          "ret": float(er.sum())})
            stats["reward"] += r
            for k in ("wrong", "miss", "true"):
                stats[k] += info.get(k, 0)
            st = st2
    return batch, stats


def train_update(policy, opt, batch, clip=0.2, epochs=4, minibatch=8):
    """逐边 PPO：每条候选边是一个独立动作，用自己的即时奖励做优势。"""
    flat = np.concatenate([f["er"] for f in batch])
    mu, sd = float(flat.mean()), float(flat.std() + 1e-8)
    for f in batch:
        f["adv"] = (f["er"] - mu) / sd

    idx = np.arange(len(batch))
    for _ in range(epochs):
        np.random.shuffle(idx)
        for s in range(0, len(idx), minibatch):
            chunk = idx[s:s + minibatch]
            opt.clear_grad()
            loss_p = loss_v = loss_e = 0.0
            for j in chunk:
                f = batch[j]
                logits, value = policy(paddle.to_tensor(f["X"]))
                lp = logp_vec(logits, f["a"])
                ratio = paddle.exp(lp - paddle.to_tensor(f["logp"]))
                adv = paddle.to_tensor(f["adv"])
                surr1 = ratio * adv
                surr2 = paddle.clip(ratio, 1 - clip, 1 + clip) * adv
                loss_p += -paddle.mean(paddle.minimum(surr1, surr2))
                loss_v += 0.5 * (value - f["ret"]) ** 2
                p = F.sigmoid(logits)
                loss_e += -0.01 * paddle.mean(
                    -(p * paddle.log(p + 1e-8) + (1 - p) * paddle.log(1 - p + 1e-8)))
            loss = (loss_p + 0.5 * loss_v + loss_e) / len(chunk)
            loss.backward()
            paddle.nn.utils.clip_grad_norm_(policy.parameters(), 0.5)
            opt.step()


def eval_policy(policy, norm, cases, detail=False):
    rows = []
    for scn, lvl, seed in cases:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=seed)
        st = env.reset()
        tot = {"reward": 0.0, "wrong": 0, "miss": 0, "true": 0}
        while not st.get("done"):
            if len(st["feats"]) == 0:
                st, _, done, _ = env.step([])
                continue
            X = norm(st["feats"])
            with paddle.no_grad():
                logits, _ = policy(paddle.to_tensor(X))
                p = F.sigmoid(logits).numpy()
            p = p * (1.0 - np.array(st["masked"], dtype=np.float32))
            a = (p >= 0.5).astype(np.int32)
            st, r, done, info = env.step_actions(list(p), list(a))
            tot["reward"] += r
            for k in ("wrong", "miss", "true"):
                tot[k] += info.get(k, 0)
        frag = env.truth_tracks
        tot["frags"] = sum(len(v) for v in frag.values()) / max(1, len(frag))
        tot["split"] = sum(1 for v in frag.values() if len(v) > 1) / max(1, len(frag))
        rows.append(tot)
    if detail:
        return rows
    return {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}


def eval_rule(cases):
    return eval_policy(_RuleProxy(), Normalizer(1), cases)


class _RuleProxy:
    """用规则分代替策略（评测同一套解码）。"""


def main() -> int:
    probe = AssociationEnv("sparse", level="noid", frames=2, seed=0)
    dim = probe.feature_dim
    print("=" * 88)
    print(" PPO（飞桨）训练航迹关联策略   特征维度 %d" % dim)
    print("=" * 88)

    norm = Normalizer(dim)
    tmp = EdgePolicy(dim)
    collect(tmp, norm, TRAIN_CASES)

    policy = EdgePolicy(dim)

    print("\n规则热启动…")
    warm_start(policy, norm, TRAIN_CASES)
    opt = paddle.optimizer.Adam(learning_rate=5e-4, parameters=policy.parameters())

    # 规则基线
    rows = []
    for scn, lvl, sd in TEST_CASES:
        env = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=sd)
        r = env.run_policy(lambda f, rule: 1.0 if rule > 0 else 0.0)
        frag = env.truth_tracks
        r["frags"] = sum(len(v) for v in frag.values()) / max(1, len(frag))
        r["split"] = sum(1 for v in frag.values() if len(v) > 1) / max(1, len(frag))
        rows.append(r)
    rule_base = {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}
    print("\n规则基线：奖励 %.1f  错配 %.0f  漏配 %.0f  碎片 %.2f  被拆 %.0f%%"
          % (rule_base["reward"], rule_base["wrong"], rule_base["miss"],
             rule_base["frags"], rule_base["split"] * 100))

    print("\n训练（每轮 5 局 × 40 帧）…")
    history = []
    for it in range(30):
        batch, stats = collect(policy, norm, TRAIN_CASES)
        train_update(policy, opt, batch)
        ev = eval_policy(policy, norm, TEST_CASES)
        history.append({"iter": it + 1, "train": stats["reward"], "test": ev["reward"],
                        "wrong": ev["wrong"], "miss": ev["miss"], "frags": ev["frags"]})
        if (it + 1) % 3 == 0 or it == 0:
            print("  iter %2d  训练 %8.1f  测试 %8.1f  错配 %3.0f  漏配 %4.0f  碎片 %.2f"
                  % (it + 1, stats["reward"], ev["reward"], ev["wrong"], ev["miss"], ev["frags"]))

    final = eval_policy(policy, norm, TEST_CASES)
    print("\n最终（测试集）")
    print("-" * 88)
    print("%-10s %10s %8s %8s %10s %10s" % ("方法", "累计奖励", "错配", "漏配", "碎片数", "被拆占比"))
    print("%-10s %10.1f %8.0f %8.0f %10.2f %9.0f%%"
          % ("规则", rule_base["reward"], rule_base["wrong"], rule_base["miss"],
             rule_base["frags"], rule_base["split"] * 100))
    print("%-10s %10.1f %8.0f %8.0f %10.2f %9.0f%%"
          % ("PPO", final["reward"], final["wrong"], final["miss"],
             final["frags"], final["split"] * 100))

    print("\n分场景")
    print("-" * 88)
    print("%-24s %10s %10s %10s" % ("场景", "规则奖励", "PPO奖励", "改进"))
    for scn, lvl, sd in TEST_CASES:
        a = AssociationEnv(scn, level=lvl, frames=FRAMES, seed=sd).run_policy(
            lambda f, r: 1.0 if r > 0 else 0.0)["reward"]
        ev = eval_policy(policy, norm, [(scn, lvl, sd)])["reward"]
        print("%-24s %10.0f %10.0f %+10.0f" % ("%s/%s" % (scn, lvl), a, ev, ev - a))

    paddle.save(policy.state_dict(), os.path.join(_HERE, "ppo_policy.pdparams"))
    json.dump(history, open(os.path.join(_HERE, "ppo_history.json"), "w",
                            encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"mean": norm.mean.tolist(), "std": norm.std.tolist(),
               "features": probe.feature_names(), "test": final, "rule": rule_base},
              open(os.path.join(_HERE, "ppo_meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n模型已保存: experiments/rl_dedup/ppo_policy.pdparams")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
