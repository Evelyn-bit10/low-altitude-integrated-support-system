# -*- coding: utf-8 -*-
"""断链降级：地面站指令丢失时，机队还能不能安全落地。

背景
----
    现在整套排序是集中式的：地面站算好"谁第几个落"，再下发。
    一旦链路丢包/中断，指令没了 —— 无人机自己该怎么办？

两种降级方式
------------
    ① 保守（等）：指令没收到 → 继续等待，另找机会
    ② 自主（自己判）：指令没收到 → 若"我 ETA 最早 且 间隔够"就自己落
                        否则减速让行
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_fcfs_slow  # noqa: E402


def run_with_loss(policy, p_loss=0.0, episodes=300, autonomous=False, seed=0):
    rng = random.Random(seed)
    tot = land = dep = viol = 0.0
    for s in range(episodes):
        env = SeqEnv(seed=s)
        st = env.reset()
        done = False
        while not done:
            a = policy(st, env)
            # 指令丢失
            if p_loss > 0 and a < env.n and rng.random() < p_loss:
                if autonomous and a < env.n:
                    # 自主降级：自己判断能不能落
                    d = env.drones[a]
                    feasible = (not d.landed) and (env.t + d.eta + 1e-6 >= env.runway_free_at)
                    a = a if feasible else env.n
                else:
                    a = env.n
            st, r, done, info = env.step(a)
            tot += r
            if info.get("separation_violation") is not None:
                viol += 1
        land += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes * 3)
    return {"land": land / n, "dep": dep / n, "viol": viol / episodes, "reward": tot / episodes}


if __name__ == "__main__":
    print("%-22s %-8s %-9s %-9s %-9s" % ("策略 / 丢包率", "落地率", "耗尽率", "间隔违规", "奖励"))
    print("-" * 68)
    for name, pol, auto in (("集中式（保守降级）", policy_fcfs_slow, False),
                            ("集中式（自主降级）", policy_fcfs_slow, True)):
        for p in (0.0, 0.1, 0.2, 0.4):
            r = run_with_loss(pol, p_loss=p, autonomous=auto)
            print("%-22s %-8s %6.1f%% %8.1f%% %9.2f %9.2f"
                  % (name, "%.0f%%" % (p * 100), r["land"] * 100, r["dep"] * 100,
                     r["viol"], r["reward"]))
