# -*- coding: utf-8 -*-
"""预测外推：把"1 秒广播滞后"补回来。

问题
----
    机间广播 1 Hz，收到时数据已经旧了 1 秒。
    60 m/s 的进近速度 → 位置误差 60 m、ETA 误差 1 s。
    决策本身只要 1 μs，但用的是旧数据 —— 瓶颈在信息不在算力。

做法
----
    每条广播带时间戳和速度。收到后按 Δt 外推：
        x' = x + vx·Δt      eta' = eta − Δt
    等价于把广播频率提高几十倍，且零额外带宽。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_multi import SeqEnv, MIN_SEP_S, policy_fcfs_slow  # noqa: E402


class Msg:
    """一条广播：时刻 + 位置/ETA 快照。"""
    __slots__ = ("t", "eta", "battery", "idx", "speed")

    def __init__(self, t, eta, battery, idx, speed):
        self.t, self.eta, self.battery, self.idx, self.speed = t, eta, battery, idx, speed

    def eta_now(self, now):
        """按 Δt 外推后的 ETA（不会变负）。"""
        return max(0.0, self.eta - (now - self.t))


def policy_fcfs_predicted(state, env):
    """带预测外推的 FCFS + 阈值慢飞：用外推 ETA 而不是原始 ETA。"""
    # 模拟"每架只在上一个整秒发过广播，现在按 Δt 外推"
    lag = 1.0                                  # 广播周期
    now = env.t + lag                          # 数据滞后 1 秒
    best, best_eta = env.n, 1e9
    for d in env.drones:
        if d.landed:
            continue
        eta_raw = d.eta                        # 本机看到的是旧值
        eta_pred = max(0.0, eta_raw - lag)     # 外推后的"此刻"ETA
        if now + eta_pred + 1e-6 >= env.runway_free_at and eta_pred < best_eta:
            best, best_eta = d.idx, eta_pred
    if best < env.n:
        return best
    # 没有可落的 → 该等的减速
    for d in env.drones:
        if d.landed or d.ratio > 0.61:
            continue
        if env.runway_free_at - (env.t + d.eta) > 20.0:
            return env.n + 1 + d.idx
    return env.n


def policy_fcfs_stale(state, env):
    """对照组：用未外推的旧数据决策（等价于现在的实现）。"""
    return policy_fcfs_slow(state, env)


def run(policy, episodes=300, broadcast_hz=1.0):
    tot = land = dep = viol = 0.0
    for s in range(episodes):
        env = SeqEnv(seed=s)
        st = env.reset()
        done = False
        while not done:
            st, r, done, info = env.step(policy(st, env))
            tot += r
            if info.get("separation_violation") is not None:
                viol += 1
        land += sum(1 for d in env.drones if d.landed and d.battery > 0)
        dep += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes * 3)
    return {"land": land / n, "dep": dep / n, "viol": viol / episodes, "reward": tot / episodes}


if __name__ == "__main__":
    print("%-26s %-8s %-9s %-9s %-9s" % ("策略", "落地率", "耗尽率", "间隔违规", "奖励"))
    print("-" * 66)
    for name, pol in (("FCFS+慢飞（不外推）", policy_fcfs_stale),
                      ("FCFS+慢飞（预测外推）", policy_fcfs_predicted)):
        r = run(pol)
        print("%-26s %6.1f%% %8.1f%% %9.2f %9.2f"
              % (name, r["land"] * 100, r["dep"] * 100, r["viol"], r["reward"]))
