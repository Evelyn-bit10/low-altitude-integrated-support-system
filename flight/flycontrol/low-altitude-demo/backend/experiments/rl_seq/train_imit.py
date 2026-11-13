# -*- coding: utf-8 -*-
"""模仿学习：用"暴力最优的顺序"当标签，训练一个排序策略。

为什么这条路最可能成功
----------------------
    暴力最优 89.7% vs FCFS 79.5% —— 有 10 个点可拿；
    但 CEM 从零学只到 73%、前瞻搜索到 71%，都拿不到。
    原因是没有"正确的示范"。这里用 6 种顺序全枚举得到精确最优，
    把每一步的"该放谁"当成标签直接学 —— 相当于请了个最优教练。

用法：
    python experiments/rl_seq/train_imit.py
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs  # noqa: E402

DIM, H, NA = 17, 32, 4


def best_order(seed):
    """枚举 6 种顺序，返回最优顺序与得分。"""
    best, best_r = None, -1e18
    for order in itertools.permutations(range(3)):
        env = SeqEnv(seed=seed)
        env.reset()
        total = 0.0
        for idx in order:
            for _ in range(200):
                d = env.drones[idx]
                if d.landed:
                    break
                if env.t + d.eta + 1e-6 >= env.runway_free_at:
                    _, r, done, _ = env.step(idx); total += r
                    break
                _, r, done, _ = env.step(env.n); total += r
                if done:
                    break
        g = 0
        while not env.done and g < 200:
            alive = [d for d in env.drones if not d.landed]
            if not alive:
                break
            _, r, done, _ = env.step(alive[0].idx); total += r; g += 1
        if total > best_r:
            best_r, best = total, order
    return best, best_r


def collect(n_episodes=400, seed0=0):
    """按最优顺序回放，记录 (状态, 正确动作)。"""
    X, Y = [], []
    for s in range(n_episodes):
        order, _ = best_order(seed0 + s)
        env = SeqEnv(seed=seed0 + s)
        st = env.reset()
        for idx in order:
            for _ in range(200):
                if env.drones[idx].landed:
                    break
                d = env.drones[idx]
                can = env.t + d.eta + 1e-6 >= env.runway_free_at
                act = idx if can else env.n
                X.append(list(st["feats"]))
                Y.append(act)
                st, r, done, _ = env.step(act)
                if done:
                    break
            if env.done:
                break
        g = 0
        while not env.done and g < 200:
            alive = [d for d in env.drones if not d.landed]
            if not alive:
                break
            X.append(list(st["feats"]))
            Y.append(alive[0].idx)
            st, r, done, _ = env.step(alive[0].idx)
            g += 1
    return np.array(X, dtype=np.float64), np.array(Y, dtype=np.int64)


def train_mlp(X, Y, iters=400, lr=0.05, seed=0):
    rng = np.random.default_rng(seed)
    W1 = rng.normal(0, 0.3, (DIM, H)); b1 = np.zeros(H)
    W2 = rng.normal(0, 0.3, (H, NA)); b2 = np.zeros(NA)
    n = len(X)
    for it in range(iters):
        idx = rng.permutation(n)
        for s in range(0, n, 64):
            b = idx[s:s + 64]
            x = X[b]
            h = np.tanh(x @ W1 + b1)
            logit = h @ W2 + b2
            logit -= logit.max(axis=1, keepdims=True)
            p = np.exp(logit); p /= p.sum(axis=1, keepdims=True)
            onehot = np.zeros_like(p); onehot[np.arange(len(b)), Y[b]] = 1
            g = (p - onehot) / len(b)
            gW2 = h.T @ g; gb2 = g.sum(axis=0)
            gh = (g @ W2.T) * (1 - h * h)
            gW1 = x.T @ gh; gb1 = gh.sum(axis=0)
            W1 -= lr * gW1; b1 -= lr * gb1
            W2 -= lr * gW2; b2 -= lr * gb2
        if it % 100 == 0:
            h = np.tanh(X @ W1 + b1)
            pred = np.argmax(h @ W2 + b2, axis=1)
            print("  iter %3d | 训练准确率 %.1f%%" % (it, (pred == Y).mean() * 100))
    return W1, b1, W2, b2


def make_policy(W1, b1, W2, b2):
    def f(state, env):
        h = np.tanh(np.asarray(state["feats"], dtype=np.float64) @ W1 + b1)
        a = int(np.argmax(h @ W2 + b2))
        # 安全兜底：模型选了"放行不可用的飞机"时改为等待
        if a < env.n:
            d = env.drones[a]
            if d.landed or env.t + d.eta + 1e-6 < env.runway_free_at:
                return env.n
        return a
    return f


def run(policy, episodes=300, seed0=90000):
    tot = land = dep = 0.0
    for s in range(episodes):
        env = SeqEnv(seed=seed0 + s)
        st = env.reset(); done = False
        while not done:
            st, r, done, _ = env.step(policy(st, env)); tot += r
        land += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes)
    return tot / n, land / (n * 3), dep / (n * 3)


if __name__ == "__main__":
    print("① 生成示范数据（暴力最优）…")
    X, Y = collect(400)
    from collections import Counter
    print("   样本 %d 条，动作分布 %s" % (len(X), dict(Counter(Y.tolist()))))

    print("\n② 训练 MLP …")
    W1, b1, W2, b2 = train_mlp(X, Y)

    print("\n③ 评估（300 局，seed 90000 起，与训练集不重叠）")
    r_imit = run(make_policy(W1, b1, W2, b2))
    r_fcfs = run(policy_fcfs)
    print("   FCFS      奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (r_fcfs[0], r_fcfs[1]*100, r_fcfs[2]*100))
    print("   模仿最优  奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (r_imit[0], r_imit[1]*100, r_imit[2]*100))
    print("   暴力最优  奖励 %8.2f | 落地 %5.1f%%（上限参考）" % (-21.04, 89.7))
