# -*- coding: utf-8 -*-
"""算这个任务的「上限」：暴力枚举所有放行顺序，看规则离最优还差多少。

N=3 时只有 3! = 6 种顺序，可以直接精确求最优。
如果最优和 FCFS 一样，那 RL 再怎么训也超不过 —— 这是判断"值不值得训"的硬标准。
"""
import copy
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_battery, MIN_SEP_S  # noqa: E402


def simulate_order(order, seed):
    """按给定顺序放行（放行后再轮到下一架），返回 (奖励, 落地数, 耗尽数)。"""
    env = SeqEnv(seed=seed)
    env.reset()
    total = 0.0
    for idx in order:
        # 等到这架可以放行（不违反间隔）
        for _ in range(200):
            d = env.drones[idx]
            if d.landed:
                break
            eta_t = env.t + d.eta
            if eta_t + 1e-6 >= env.runway_free_at:
                _, r, done, _ = env.step(idx)
                total += r
                break
            _, r, done, _ = env.step(env.n)      # 等待
            total += r
            if done:
                break
    # 收尾：把剩下的落地（或耗尽）
    guard = 0
    while not env.done and guard < 200:
        alive = [d for d in env.drones if not d.landed]
        if not alive:
            break
        _, r, done, _ = env.step(alive[0].idx)
        total += r
        guard += 1
    landed = sum(1 for d in env.drones if d.landed and d.battery > 0)
    dep = sum(1 for d in env.drones if d.battery <= 0)
    return total, landed, dep


def policy_edf(state, env):
    """EDF：按"电量耗尽的时刻"排序（deadline = 剩余电量/耗电率）。"""
    best, best_dl = env.n, 1e9
    for d in env.drones:
        if d.landed:
            continue
        if env.t + d.eta + 1e-6 < env.runway_free_at:
            continue
        deadline = d.battery / 0.0035          # 还能等多少秒
        if deadline < best_dl:
            best, best_dl = d.idx, deadline
    return best if best < env.n else env.n


def policy_lookahead(state, env, depth=3):
    """一步/多步前瞻：对每个动作向后模拟 depth 步（rollout 用 FCFS），选总收益最高的。"""
    best_a, best_v = env.n, -1e9
    for a in range(env.n + 1):
        e2 = copy.deepcopy(env)
        st, r, done, _ = e2.step(a)
        v = r
        d = 1
        while not done and d < depth:
            st, r2, done, _ = e2.step(policy_fcfs(st, e2))
            v += r2
            d += 1
        if v > best_v:
            best_v, best_a = v, a
    return best_a


def run(policy, episodes=200, seed0=70000):
    tot = land = dep = 0.0
    for s in range(episodes):
        env = SeqEnv(seed=seed0 + s)
        st = env.reset()
        done = False
        while not done:
            st, r, done, _ = env.step(policy(st, env))
            tot += r
        land += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes)
    return tot / n, land / (n * 3), dep / (n * 3)


def run_optimal(episodes=200, seed0=70000):
    tot = land = dep = 0.0
    for s in range(episodes):
        best = None
        for order in itertools.permutations(range(3)):
            r = simulate_order(order, seed0 + s)
            if best is None or r[0] > best[0]:
                best = r
        tot += best[0]
        land += best[1]
        dep += best[2]
    n = float(episodes)
    return tot / n, land / (n * 3), dep / (n * 3)


if __name__ == "__main__":
    for name, fn in (("FCFS", run),
                     ("EDF(正确实现)", run),
                     ("电量优先", run)):
        pol = {"FCFS": policy_fcfs, "EDF(正确实现)": policy_edf, "电量优先": policy_battery}[name]
        r = fn(pol)
        print("%-14s | 奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%" % (name, r[0], r[1] * 100, r[2] * 100))
    for depth in (2, 3, 4):
        r = run(lambda st, env, d=depth: policy_lookahead(st, env, d))
        print("%-14s | 奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%"
              % ("前瞻 depth=%d" % depth, r[0], r[1] * 100, r[2] * 100))
    o = run_optimal()
    print("%-14s | 奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%   ← 这个任务的**理论上限**"
          % ("暴力最优(6种顺序)", o[0], o[1] * 100, o[2] * 100))
