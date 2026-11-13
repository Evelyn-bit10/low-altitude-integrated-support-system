# -*- coding: utf-8 -*-
"""跑基线：这个任务值不值得上 RL。"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env import RouteEnv, policy_always_continue, policy_greedy  # noqa: E402


def run(policy, episodes=300, rain=0.0):
    total = 0.0
    arrived = depleted = lost = 0
    for s in range(episodes):
        env = RouteEnv(seed=s, rain=rain)
        st = env.reset()
        done = False
        info = {}
        while not done:
            st, r, done, info = env.step(policy(st, env))
            total += r
        if info.get("end") == "arrived":
            arrived += 1
        if info.get("end") == "battery_depleted":
            depleted += 1
        if st["retreat_lost"]:
            lost += 1
    n = float(episodes)
    return {"avg": total / n, "arrive": arrived / n, "depleted": depleted / n, "lost": lost / n}


def random_policy(state, env):
    return random.randint(0, 3)


if __name__ == "__main__":
    random.seed(0)
    for name, pol in (("随机", random_policy),
                      ("一直飞", policy_always_continue),
                      ("规则基线", policy_greedy)):
        for rain in (0.0, 8.0):
            r = run(pol, rain=rain)
            print("%-8s rain=%2.0f | reward %7.2f | arrive %5.1f%% | depleted %5.1f%% | retreat_lost %5.1f%%"
                  % (name, rain, r["avg"], r["arrive"] * 100, r["depleted"] * 100, r["lost"] * 100))
