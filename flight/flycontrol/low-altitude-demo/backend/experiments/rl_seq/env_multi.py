# -*- coding: utf-8 -*-
"""多机进近排序的强化学习环境（真正的序贯决策）。

为什么这个任务比"单机选航道"更值得 RL
------------------------------------
    单机选航道：代价可算、一次性 → 枚举+物理模型更优（已实测）
    多机排序：谁的决策都会改变别人的等待时间，而且"再等一会儿"的代价
             随电量/间隔累积 —— 规则很难写好，这才是 RL 的战场。

模型
----
    N 架无人机同时进近，共用一条跑道，必须保持最小间隔。
    每一步由"调度器"决定：放行哪一架（或全部等待）。
    放行后该机落地退出；等待中的每架按秒耗电。

状态（每架 5 维 × N + 全局 2 维）
    距离跑道 km / 10、剩余电量、速度/20、已等待秒/60、是否可立即落地
    + 剩余架数/N、跑道空闲时间/60

动作：N+1 个（放行第 i 架 / 继续等待）
奖励：放行且安全 +10；违反间隔 −50；某架电量耗尽 −100；每秒等待 −0.05×架数
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

MIN_SEP_S = 45.0        # 最小尾流/时间间隔（秒）
APPROACH_SPEED = 60.0   # m/s（进近段）
BATTERY_DRAIN = 0.0040  # 盘旋等待时的每秒耗电（慢飞耗电 ∝ ratio²）
SLOW_DRAIN = 0.0014     # 慢飞巡航时的每秒耗电（比盘旋省 60%）
N_DRONES = 3


class Drone:
    __slots__ = ("idx", "dist_m", "battery", "speed", "waited", "landed", "slowed", "ratio")

    def __init__(self, idx: int, dist_m: float, battery: float, speed: float):
        self.idx = idx
        self.dist_m = dist_m
        self.battery = battery
        self.speed = speed
        self.waited = 0.0
        self.landed = False
        self.slowed = False
        self.ratio = 1.0         # 当前速度比（1.0 / 0.7 / 0.5）：耗电 ∝ ratio²

    @property
    def eta(self) -> float:
        return self.dist_m / max(self.speed * self.ratio, 1.0)


class SeqEnv:
    def __init__(self, seed: int = 0, n: int = N_DRONES):
        self.rng = random.Random(seed)
        self.n = n
        self.reset()

    def reset(self) -> Dict:
        rng = self.rng
        self.drones: List[Drone] = [
            Drone(i, rng.uniform(800, 4000), rng.uniform(0.12, 0.6), rng.uniform(50, 70))
            for i in range(self.n)
        ]
        self.runway_free_at = 0.0     # 跑道下次可用的仿真时刻
        self.t = 0.0
        self.steps = 0
        self.done = False
        self.ep_return = 0.0
        return self._state()

    # ------------------------------------------------------------ 状态
    def _state(self) -> Dict:
        feats: List[float] = []
        alive = [d for d in self.drones if not d.landed]
        for d in self.drones:
            if d.landed:
                feats.extend([0.0, 0.0, 0.0, 0.0, 0.0])
            else:
                can_land = 1.0 if (self.t + d.eta) >= self.runway_free_at else 0.0
                feats.extend([min(d.dist_m / 10000.0, 1.0), max(d.battery, 0.0),
                              d.speed / 100.0, min(d.waited / 60.0, 1.0), can_land])
        feats.append(len(alive) / float(self.n))
        feats.append(min(max(self.runway_free_at - self.t, 0.0) / 60.0, 1.0))
        return {"feats": feats, "done": self.done,
                "alive": len(alive), "battery": [round(d.battery, 3) for d in self.drones]}

    @property
    def feature_dim(self) -> int:
        return self.n * 5 + 2

    @property
    def n_actions(self) -> int:
        return self.n + 1 + self.n      # 放行 i / 等待 / 让 i 减速

    # ------------------------------------------------------------ 步进
    def step(self, action: int) -> Tuple[Dict, float, bool, Dict]:
        if self.done:
            return self._state(), 0.0, True, {}
        info: Dict = {}
        alive = [d for d in self.drones if not d.landed]
        reward = -0.05 * len(alive)          # 等待成本

        # 让第 i 架减速（action = n+1+i）
        if action >= self.n + 1:
            k = action - self.n - 1
            if 0 <= k < self.n and not self.drones[k].landed:
                self.drones[k].slowed = True
                self.drones[k].ratio = max(0.5, round(self.drones[k].ratio * 0.6, 2))
                info["slowed"] = k

        # 时间推进到"下一步"：等待 5 秒
        dt = 5.0
        self.t += dt
        for d in alive:
            d.waited += dt
            d.battery -= BATTERY_DRAIN * (d.ratio ** 2) * dt
            d.dist_m = max(0.0, d.dist_m - d.speed * dt * 0.15)   # 盘旋/减速接近

        # 电量耗尽
        for d in alive:
            if d.battery <= 0:
                d.landed = True
                reward -= 100.0
                info["depleted"] = d.idx

        alive = [d for d in self.drones if not d.landed]
        if action < self.n:
            d = self.drones[action]
            if not d.landed:
                eta_t = self.t + d.eta
                if eta_t + 1e-6 >= self.runway_free_at:
                    d.landed = True
                    self.runway_free_at = max(self.t, eta_t) + MIN_SEP_S
                    reward += 10.0 * max(0.0, d.battery) + 2.0
                    info["landed"] = d.idx
                else:
                    reward -= 50.0                 # 违反间隔
                    info["separation_violation"] = d.idx

        alive = [d for d in self.drones if not d.landed]
        if not alive:
            self.done = True
            info["end"] = "all_landed"
        elif self.t > 600:
            self.done = True
            reward -= 20.0
            info["end"] = "timeout"

        self.steps += 1
        self.ep_return += reward
        return self._state(), reward, self.done, info


# ------------------------------------------------------------------ 基线
def policy_fcfs(state, env) -> int:
    """先到先服务：放行 ETA 最早的（且不违反间隔）。"""
    best, best_eta = env.n, 1e9
    for d in env.drones:
        if d.landed:
            continue
        eta_t = env.t + d.eta
        if eta_t + 1e-6 >= env.runway_free_at and d.eta < best_eta:
            best, best_eta = d.idx, d.eta
    return best if best < env.n else env.n


def policy_battery(state, env) -> int:
    """电量优先：先放行电量最低的（救急）。"""
    best, best_b = env.n, 9.9
    for d in env.drones:
        if d.landed:
            continue
        if env.t + d.eta + 1e-6 >= env.runway_free_at and d.battery < best_b:
            best, best_b = d.idx, d.battery
    return best if best < env.n else env.n


def policy_fcfs_slow(state, env) -> int:
    """FCFS + 慢飞：能把等待耗电降 60%，这是提升落地率最直接的手段。"""
    for d in env.drones:
        if not d.landed and not d.slowed and env.t + d.eta + 1e-6 < env.runway_free_at:
            return env.n + 1 + d.idx            # 先让等着的减速
    return policy_fcfs(state, env)


def policy_fcfs_jit(state, env) -> int:
    """动态调速（Just-In-Time）：把还要等的那架降到"刚好不早到"的档位。"""
    for d in env.drones:
        if d.landed:
            continue
        wait = env.runway_free_at - (env.t + d.eta)
        # 保守：只在"确实要等很久"时降一档，且最低到 0.6（不再往下）
        if wait > 60.0 and d.ratio > 0.61:
            return env.n + 1 + d.idx
    return policy_fcfs(state, env)


def run(policy, episodes: int = 300):
    total, landed, depleted = 0.0, 0, 0
    for s in range(episodes):
        env = SeqEnv(seed=s)
        st = env.reset()
        done = False
        info = {}
        while not done:
            st, r, done, info = env.step(policy(st, env))
            total += r
        landed += sum(1 for d in env.drones if d.landed and d.battery > 0)
        depleted += sum(1 for d in env.drones if d.battery <= 0)
    n = float(episodes * N_DRONES)
    return {"avg": total / episodes, "landed_rate": landed / n, "depleted_rate": depleted / n}


if __name__ == "__main__":
    random.seed(0)
    def rnd(state, env):
        return random.randint(0, env.n)

    for name, pol in (("随机", rnd), ("先到先服务", policy_fcfs),
                      ("电量优先", policy_battery), ("FCFS+慢飞(固定)", policy_fcfs_slow),
                      ("FCFS+动态调速", policy_fcfs_jit)):
        r = run(pol)
        print("%-10s | 奖励 %8.2f | 落地率 %5.1f%% | 电量耗尽 %5.1f%%"
              % (name, r["avg"], r["landed_rate"] * 100, r["depleted_rate"] * 100))
