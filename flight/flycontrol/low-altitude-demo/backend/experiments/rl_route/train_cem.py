# -*- coding: utf-8 -*-
"""用 CEM（交叉熵方法）训练航道改航策略。

为什么先用 CEM 而不是 PPO：
    动作只有 4 个、状态 11 维，CEM 几行就能跑通，且没有超参陷阱；
    等确认"这个任务确实有可学的空间"，再换 PPO 提精度。

用法：
    python experiments/rl_route/train_cem.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env import RouteEnv, policy_always_continue, policy_greedy  # noqa: E402

DIM, H1, H2, NA = 11, 32, 32, 4


def unpack(theta):
    i = 0
    def take(n):
        nonlocal i
        out = theta[i:i + n]
        i += n
        return out
    W1 = take(DIM * H1).reshape(DIM, H1)
    b1 = take(H1)
    W2 = take(H1 * H2).reshape(H1, H2)
    b2 = take(H2)
    W3 = take(H2 * NA).reshape(H2, NA)
    b3 = take(NA)
    return W1, b1, W2, b2, W3, b3


def logits(theta, feats):
    W1, b1, W2, b2, W3, b3 = unpack(theta)
    x = np.asarray(feats, dtype=np.float64)
    h = np.tanh(x @ W1 + b1)
    h = np.tanh(h @ W2 + b2)
    return h @ W3 + b3


def policy(theta):
    def f(state, env):
        return int(np.argmax(logits(theta, state["feats"])))
    return f


def evaluate(theta, episodes=200, rain=0.0):
    total = 0.0
    arrived = 0
    for s in range(episodes):
        env = RouteEnv(seed=10000 + s, rain=rain)
        st = env.reset()
        done = False
        info = {}
        while not done:
            st, r, done, info = env.step(policy(theta)(st, env))
            total += r
        if info.get("end") == "arrived":
            arrived += 1
    return total / episodes, arrived / episodes


def run_baselines(episodes=200, rain=0.0):
    out = {}
    for name, pol in (("一直飞", policy_always_continue), ("规则基线", policy_greedy)):
        total, arr = 0.0, 0
        for s in range(episodes):
            env = RouteEnv(seed=10000 + s, rain=rain)
            st = env.reset()
            done = False
            info = {}
            while not done:
                st, r, done, info = env.step(pol(st, env))
                total += r
            if info.get("end") == "arrived":
                arr += 1
        out[name] = (total / episodes, arr / episodes)
    return out


def train(iters=120, pop=40, elite=8, episodes=6, seed=0):
    rng = np.random.default_rng(seed)
    n_par = DIM * H1 + H1 + H1 * H2 + H2 + H2 * NA + NA
    mu = np.zeros(n_par)
    sigma = np.full(n_par, 0.5)
    best_theta, best_score = None, -1e9

    for it in range(iters):
        cands = [mu + sigma * rng.standard_normal(n_par) for _ in range(pop)]
        scores = []
        for th in cands:
            tot = 0.0
            for e in range(episodes):
                env = RouteEnv(seed=it * 1000 + e, rain=6.0 if e % 2 else 0.0)
                st = env.reset()
                done = False
                while not done:
                    st, r, done, _ = env.step(policy(th)(st, env))
                    tot += r
            scores.append(tot / episodes)
        order = np.argsort(scores)[::-1]
        elite_set = np.array([cands[k] for k in order[:elite]])
        mu = elite_set.mean(axis=0)
        sigma = elite_set.std(axis=0) + 1e-3
        if scores[order[0]] > best_score:
            best_score = scores[order[0]]
            best_theta = elite_set[0].copy()
        if it % 10 == 0 or it == iters - 1:
            ev, arr = evaluate(best_theta, episodes=100)
            print("  iter %3d | 训练分 %7.2f | 验证奖励 %7.2f | 送达 %5.1f%%" %
                  (it, best_score, ev, arr * 100))
    return best_theta


if __name__ == "__main__":
    print("基线：")
    base = run_baselines()
    for k, (r, a) in base.items():
        print("  %-6s 奖励 %7.2f | 送达 %5.1f%%" % (k, r, a * 100))

    print("\nCEM 训练：")
    theta = train()
    ev, arr = evaluate(theta, episodes=300)
    print("\n结果对比（300 局）：")
    print("  一直飞    奖励 %7.2f | 送达 %5.1f%%" % (base["一直飞"][0], base["一直飞"][1] * 100))
    print("  规则基线  奖励 %7.2f | 送达 %5.1f%%" % (base["规则基线"][0], base["规则基线"][1] * 100))
    print("  CEM 策略  奖励 %7.2f | 送达 %5.1f%%" % (ev, arr * 100))
