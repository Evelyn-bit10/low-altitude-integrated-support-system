# -*- coding: utf-8 -*-
"""两个"更高效"的模型：
    ① 线性打分排序（4 个参数，替代 1600 参数的 MLP）
    ② 参数化阈值网格搜索（替代 RL 做动态调速）
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_fcfs_slow  # noqa: E402
from train_imit import collect, train_mlp, make_policy, run  # noqa: E402
from env_multi import policy_fcfs_jit  # noqa: E402


def drone_feats(state, env):
    """把 17 维状态拆成每架的 4 维打分特征：[ETA, 电量, 已等待, 能否立即落]。"""
    out = []
    for d in env.drones:
        if d.landed:
            out.append(None)
        else:
            can = 1.0 if (env.t + d.eta + 1e-6 >= env.runway_free_at) else 0.0
            out.append([d.eta / 100.0, d.battery, d.waited / 60.0, can])
    return out


def collect_pairwise(n_episodes=400, seed0=0):
    """收集 (每架特征矩阵, 正确放行的索引)，来自最优顺序的示范。"""
    from train_imit import best_order
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
                feats = drone_feats(st, env)
                if can and feats[idx] is not None:
                    X.append(feats)
                    Y.append(idx)
                st, r, done, _ = env.step(idx if can else env.n)
                if done:
                    break
            if env.done:
                break
    return X, Y


def train_linear(X, Y, iters=300, lr=0.5):
    """softmax over drones（只在可放行的架子里选）。"""
    w = np.zeros(4)
    for it in range(iters):
        g = np.zeros(4)
        for feats, label in zip(X, Y):
            avail = [i for i, f in enumerate(feats) if f is not None and f[3] > 0.5]
            if label not in avail:
                continue
            mat = np.array([feats[i] for i in avail])
            sc = mat @ w
            sc -= sc.max()
            p = np.exp(sc); p /= p.sum()
            k = avail.index(label)
            d = p.copy(); d[k] -= 1.0
            g += d @ mat
        w -= lr * g / max(1, len(X))
    return w


def make_linear_policy(w):
    def f(state, env):
        avail, best, best_s = [], env.n, -1e9
        feats = drone_feats(state, env)
        for i, ft in enumerate(feats):
            if ft is None or ft[3] < 0.5:
                continue
            s = float(np.dot(w, ft))
            if s > best_s:
                best, best_s = i, s
        return best
    return f


def policy_threshold(T, use_slow=True):
    """参数化策略：等超过 T 秒就慢飞（每 T 生效一次）。"""
    def f(state, env):
        if use_slow:
            for d in env.drones:
                if d.landed or d.ratio < 0.61:
                    continue
                wait = env.runway_free_at - (env.t + d.eta)
                if wait > T:
                    return env.n + 1 + d.idx
        return policy_fcfs(state, env)
    return f


if __name__ == "__main__":
    print("① 线性打分模型（4 个参数）")
    X, Y = collect_pairwise(400)
    print("   样本 %d 条" % len(X))
    w = train_linear(X, Y)
    print("   学到的权重 [ETA, 电量, 已等待, 可落] = %s" % np.round(w, 3).tolist())
    r_lin = run(make_linear_policy(w))
    print("   线性打分  奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (r_lin[0], r_lin[1]*100, r_lin[2]*100))

    print("\n② 阈值网格搜索（触发秒数 T）")
    best = None
    for T in (20, 40, 60, 80):
        r = run(policy_threshold(T))
        print("   T=%2ds  落地 %5.1f%% | 耗尽 %5.1f%% | 奖励 %8.2f" % (T, r[1]*100, r[2]*100, r[0]))
        if best is None or r[1] > best[1][1]:
            best = (T, r)

    print("\n③ 对比")
    r_f = run(policy_fcfs)
    r_s = run(policy_fcfs_slow)
    print("   FCFS             落地 %5.1f%%" % (r_f[1]*100))
    print("   FCFS+慢飞(固定)   落地 %5.1f%%" % (r_s[1]*100))
    print("   最优阈值 T=%ds    落地 %5.1f%%" % (best[0], best[1][1]*100))
