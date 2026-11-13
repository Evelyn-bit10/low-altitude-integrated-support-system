# -*- coding: utf-8 -*-
"""Learning to Rank：直接学两两顺序，补上线性模型欠的"相对比较"能力。

思路
----
    线性打分只看"单架绝对分数"，无法表达"两架 ETA 很接近时谁该先"。
    这里改成 pairwise：对每对 (选中 a, 未选中 b)，要求 score(a) > score(b)，
    用 logistic 损失训练，特征里显式加入**相对量**（差值）。

特征（每对 6 维，不是每架 4 维）
    ΔETA、Δ电量、Δ已等待、ETA_min、电量_min、并列度(1/(1+|ΔETA|))
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_fcfs_slow  # noqa: E402
from train_imit import best_order, run  # noqa: E402


def drone_feats(state, env):
    out = []
    for d in env.drones:
        if d.landed:
            out.append(None)
        else:
            can = 1.0 if (env.t + d.eta + 1e-6 >= env.runway_free_at) else 0.0
            out.append((d.eta / 100.0, d.battery, d.waited / 60.0, can))
    return out


def pair_feat(fa, fb):
    deta = fa[0] - fb[0]
    dbat = fa[1] - fb[1]
    dw = fa[2] - fb[2]
    return [deta, dbat, dw, min(fa[0], fb[0]),
            min(fa[1], fb[1]), 1.0 / (1.0 + abs(deta) * 10.0)]


def collect_pairs(n_episodes=400, seed0=0):
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
                if can:
                    feats = drone_feats(st, env)
                    avail = [i for i, f in enumerate(feats) if f is not None and f[3] > 0.5]
                    if idx in avail and len(avail) > 1:
                        for j in avail:
                            if j == idx:
                                continue
                            X.append(pair_feat(feats[idx], feats[j]))
                            Y.append(1.0)          # idx 优于 j
                st, r, done, _ = env.step(idx if can else env.n)
                if done:
                    break
            if env.done:
                break
    return np.array(X, dtype=np.float64), np.array(Y, dtype=np.float64)


def train_rank(X, Y, iters=400, lr=0.5):
    w = np.zeros(X.shape[1])
    n = len(X)
    for it in range(iters):
        s = X @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(s, -30, 30)))
        g = X.T @ (p - Y) / n
        w -= lr * g
        if it % 100 == 0:
            acc = ((p > 0.5) == (Y > 0.5)).mean()
            print("   iter %3d | 成对准确率 %.1f%%" % (it, acc * 100))
    return w


def make_rank_policy(w):
    def f(state, env):
        feats = drone_feats(state, env)
        avail = [i for i, ft in enumerate(feats) if ft is not None and ft[3] > 0.5]
        if not avail:
            return env.n
        if len(avail) == 1:
            return avail[0]
        # 每个候选 vs 其它候选的平均胜率
        best, best_s = env.n, -1e9
        for i in avail:
            sc = 0.0
            for j in avail:
                if i == j:
                    continue
                sc += float(np.dot(w, pair_feat(feats[i], feats[j])))
            sc /= max(1, len(avail) - 1)
            if sc > best_s:
                best, best_s = i, sc
        return best
    return f


def policy_threshold(T):
    def f(state, env):
        for d in env.drones:
            if d.landed or d.ratio < 0.61:
                continue
            if env.runway_free_at - (env.t + d.eta) > T:
                return env.n + 1 + d.idx
        return policy_fcfs(state, env)
    return f


def wrap(rank_pol):
    """排序用 LTR，等待用阈值慢飞。"""
    def f(state, env):
        a = rank_pol(state, env)
        if a == env.n:
            for d in env.drones:
                if not d.landed and d.ratio > 0.61:
                    if env.runway_free_at - (env.t + d.eta) > 20.0:
                        return env.n + 1 + d.idx
        return a
    return f


if __name__ == "__main__":
    print("① 收集成对数据 …")
    X, Y = collect_pairs(400)
    print("   %d 对样本，%d 维特征" % (len(X), X.shape[1]))

    print("\n② 训练 pairwise 模型 …")
    w = train_rank(X, Y)
    print("   权重 = %s" % np.round(w, 3).tolist())

    print("\n③ 评估（300 局）")
    r_rank = run(make_rank_policy(w))
    r_rank_slow = run(wrap(make_rank_policy(w)))
    r_fcfs = run(policy_fcfs)
    r_fcfs_slow = run(policy_fcfs_slow)
    r_thr = run(policy_threshold(20))
    print("   FCFS              落地 %5.1f%%" % (r_fcfs[1] * 100))
    print("   FCFS+慢飞         落地 %5.1f%%" % (r_fcfs_slow[1] * 100))
    print("   阈值T=20          落地 %5.1f%%" % (r_thr[1] * 100))
    print("   LTR 排序          落地 %5.1f%%" % (r_rank[1] * 100))
    print("   LTR + 阈值慢飞    落地 %5.1f%%  ← 组合" % (r_rank_slow[1] * 100))
