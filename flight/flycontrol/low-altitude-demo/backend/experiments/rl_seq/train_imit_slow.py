# -*- coding: utf-8 -*-
"""模仿学习 + 慢飞：把"谁先落"和"怎么等"两个杠杆合起来。

背景
----
    单靠排序（模仿学习）    落地 90.2%
    单靠慢飞（固定规则）    落地 98.4%
    这里验证：两者叠加能不能更高 —— 前者决定"顺序"，后者决定"等待方式"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, policy_fcfs, policy_fcfs_slow  # noqa: E402
from train_imit import collect, train_mlp, make_policy, run    # noqa: E402


def wrap_with_slow(imit_policy):
    """模仿策略决定"谁先落"；一旦它选择等待，就把该等的飞机先减速。"""
    def f(state, env):
        a = imit_policy(state, env)
        if a == env.n:                     # 想等待 → 先给等待中的飞机减速
            for d in env.drones:
                if not d.landed and not d.slowed and env.t + d.eta + 1e-6 < env.runway_free_at:
                    return env.n + 1 + d.idx
        return a
    return f


if __name__ == "__main__":
    print("① 训练模仿策略（教师 = 暴力最优顺序）…")
    X, Y = collect(400)
    W1, b1, W2, b2 = train_mlp(X, Y)
    imit = make_policy(W1, b1, W2, b2)

    print("\n② 四种策略对比（300 局，seed 90000 起）")
    rows = [
        ("FCFS",                policy_fcfs),
        ("模仿学习（仅排序）",    imit),
        ("FCFS + 慢飞",          policy_fcfs_slow),
        ("模仿学习 + 慢飞",       wrap_with_slow(imit)),
    ]
    for name, pol in rows:
        r = run(pol)
        print("  %-18s 奖励 %8.2f | 落地 %5.1f%% | 耗尽 %5.1f%%"
              % (name, r[0], r[1] * 100, r[2] * 100))
