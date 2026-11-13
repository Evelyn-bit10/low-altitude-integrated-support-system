# -*- coding: utf-8 -*-
"""多机进近排序策略训练（CEM）。

上一轮学到的教训：
    ① CEM 会过早塌缩（σ 掉到 1e-3 就再也探索不动）→ 本轮加 σ 下限
    ② 训练分和验证分能差 60 分 → 本轮按**验证集**选最优，训练只用来看趋势
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_battery  # noqa: E402

DIM, H1, H2, NA = 17, 32, 32, 4


def unpack(th):
    i = 0
    def take(n):
        nonlocal i
        out = th[i:i + n]; i += n; return out
    return (take(DIM * H1).reshape(DIM, H1), take(H1),
            take(H1 * H2).reshape(H1, H2), take(H2),
            take(H2 * NA).reshape(H2, NA), take(NA))


def act(th, feats):
    W1, b1, W2, b2, W3, b3 = unpack(th)
    x = np.asarray(feats, dtype=np.float64)
    h = np.tanh(x @ W1 + b1)
    h = np.tanh(h @ W2 + b2)
    return int(np.argmax(h @ W3 + b3))


def evaluate(th, episodes=300, base_seed=50000):
    total, landed, dep = 0.0, 0, 0
    for s in range(episodes):
        env = SeqEnv(seed=base_seed + s)
        st = env.reset()
        done = False
        while not done:
            st, r, done, _ = env.step(act(th, st["feats"]))
            total += r
        landed += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes * 3)
    return total / episodes, landed / n, dep / n


def base_line(pol, episodes=300, base_seed=50000):
    total, landed, dep = 0.0, 0, 0
    for s in range(episodes):
        env = SeqEnv(seed=base_seed + s)
        st = env.reset()
        done = False
        while not done:
            st, r, done, _ = env.step(pol(st, env))
            total += r
        landed += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes * 3)
    return total / episodes, landed / n, dep / n


def train(iters=100, pop=40, elite=8, eps=6, seed=0, sigma_floor=0.03):
    rng = np.random.default_rng(seed)
    n_par = DIM * H1 + H1 + H1 * H2 + H2 + H2 * NA + NA
    mu = np.zeros(n_par)
    sigma = np.full(n_par, 0.4)
    best_th, best_val = None, -1e9

    for it in range(iters):
        cands = [mu + sigma * rng.standard_normal(n_par) for _ in range(pop)]
        scores = []
        for th in cands:
            tot = 0.0
            for e in range(eps):
                env = SeqEnv(seed=it * 500 + e)
                st = env.reset()
                done = False
                while not done:
                    st, r, done, _ = env.step(act(th, st["feats"]))
                    tot += r
            scores.append(tot / eps)
        order = np.argsort(scores)[::-1]
        elite_set = np.array([cands[k] for k in order[:elite]])
        mu = elite_set.mean(axis=0)
        # σ 下限：防止过早塌缩
        sigma = np.maximum(elite_set.std(axis=0), sigma_floor * (1.0 - it / (iters * 1.2)))
        sigma = np.maximum(sigma, 0.01)

        if it % 10 == 0 or it == iters - 1:
            v, lr, dr = evaluate(mu, episodes=120)
            if v > best_val:
                best_val, best_th = v, mu.copy()
            print("  iter %3d | 训练 %8.2f | 验证 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%"
                  % (it, scores[order[0]], v, lr * 100, dr * 100))
    return best_th if best_th is not None else mu


if __name__ == "__main__":
    f = base_line(policy_fcfs)
    b = base_line(policy_battery)
    print("基线（300 局，seed 50000+）：")
    print("  先到先服务  奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (f[0], f[1] * 100, f[2] * 100))
    print("  电量优先    奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (b[0], b[1] * 100, b[2] * 100))

    print("\nCEM 训练：")
    th = train()
    v, lr, dr = evaluate(th, episodes=300)
    print("\n结果（300 局）：")
    print("  先到先服务  奖励 %8.2f | 落地 %5.1f%%" % (f[0], f[1] * 100))
    print("  电量优先    奖励 %8.2f | 落地 %5.1f%%" % (b[0], b[1] * 100))
    print("  CEM 策略    奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (v, lr * 100, dr * 100))
