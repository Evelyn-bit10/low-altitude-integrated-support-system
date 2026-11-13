# -*- coding: utf-8 -*-
"""航道动态改航的强化学习环境（边飞边决策）。

和"给个位置选航道"不同，这里决策是**序贯**的：
    电量在消耗、风在变，每 10 秒要决定「继续 / 换航道 / 就近备降」。
    改早了绕远，改晚了没退路 —— 代价延迟显现，这正是 RL 的主场。

状态 11 维（先做小，便于验证）
    0 进度            已飞航程 / 总航程
    1 剩余电量%       0~1
    2 沿航向风速      m/s（正=顺风）
    3 侧风            m/s
    4 当前航道剩余能耗需求 / 剩余电量
    5 备选A 的需求比
    6 备选B 的需求比
    7 当前航道最小超障 / 100m
    8 备选A 最小超障 / 100m
    9 退路余量        (剩余电量 − 飞回备降点能耗) / 满电
   10 已改航次数 / 3

动作 4 个
    0 继续当前航道
    1 切换到备选 A
    2 切换到备选 B
    3 就近备降（结束本局）

奖励
    每步 −0.02                                    时间/能耗成本
    抵达  +10 × 剩余电量                             鼓励省电
    电量耗尽 −100（终止）
    退路丢失 −30（一次性，不终止）
    切换航道 −1.0 × 进度                           越晚改越贵
    不可达航道 −50（该航道需求 > 剩余电量，强制无效）
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

BATTERY_WH = 420.0     # 收紧到临界：2.5km 就要用掉 ~90%
BASE_WH_PER_KM = 145.0        # 无风巡航 ~2.5km 耗 378Wh ≈ 151 Wh/km
CRUISE_SPEED = 15.0
DT = 10.0                     # 每步 10 秒


class Route:
    """一条候选航道（本环境用解析模型，不跑 A*，便于秒级训练）。"""

    __slots__ = ("name", "length_m", "clearance_m", "heading")

    def __init__(self, name: str, length_m: float, clearance_m: float, heading: float):
        self.name = name
        self.length_m = length_m
        self.clearance_m = clearance_m
        self.heading = heading

    def need_wh(self, wind_along: float, rain: float = 0.0) -> float:
        """飞完全程需要的电量：逆风地速下降 → 单位里程能耗上升。"""
        ground = max(CRUISE_SPEED + wind_along, 4.0)
        factor = CRUISE_SPEED / ground * (1.0 + 0.12 * min(rain / 10.0, 1.5))
        return BASE_WH_PER_KM * (self.length_m / 1000.0) * factor


class RouteEnv:
    """一局 = 一次飞行；每 DT 秒决策一次。"""

    def __init__(self, seed: int = 0, rain: float = 0.0):
        self.rng = random.Random(seed)
        self.rain = rain
        self.reset()

    # ------------------------------------------------------------ 初始化
    def reset(self) -> Dict:
        rng = self.rng
        base_hdg = rng.uniform(0, 360)
        # 三条候选航道：不同长度 / 超障余度 / 朝向
        self.routes: List[Route] = [
            Route("主航道", rng.uniform(2000, 2600), rng.uniform(90, 400), base_hdg),
            Route("备选A", rng.uniform(2600, 3400), rng.uniform(120, 450), (base_hdg + 40) % 360),
            Route("备选B", rng.uniform(3200, 4200), rng.uniform(150, 500), (base_hdg - 45) % 360),
        ]
        self.cur = 0
        self.battery = 1.0
        self.progress = 0.0
        self.wind_speed = rng.uniform(0, 10)
        self.wind_dir = rng.uniform(0, 360)
        self.switches = 0
        self.retreat_lost = False
        self.done = False
        self.blocked = False
        self.event_step = rng.randint(4, 14)
        self.event_type = rng.choice(["block", "gust", "rain"])
        self.event_fired = False
        self.steps = 0
        self.max_steps = 60
        self.ep_return = 0.0
        return self._state()

    # ------------------------------------------------------------ 风
    def _wind_components(self) -> Tuple[float, float]:
        r = self.routes[self.cur]
        delta = math.radians((self.wind_dir - r.heading + 180.0) % 360.0 - 180.0)
        return (self.wind_speed * math.cos(delta),      # 顺风为正
                self.wind_speed * math.sin(delta))      # 侧风

    def _retreat_margin(self) -> float:
        """剩余电量 − 从当前位置直飞回起降点的能耗（按剩余航程的一半估）。"""
        back_km = (self.routes[self.cur].length_m * (1.0 - self.progress)) / 1000.0
        return self.battery - BASE_WH_PER_KM * back_km / BATTERY_WH

    # ------------------------------------------------------------ 状态
    def _state(self) -> Dict:
        wind_along, wind_cross = self._wind_components()
        r = self.routes[self.cur]
        rem_wh = max(self.battery, 1e-6) * BATTERY_WH
        rem_km = r.length_m * (1.0 - self.progress) / 1000.0
        need_cur = BASE_WH_PER_KM * rem_km * (CRUISE_SPEED / max(CRUISE_SPEED + wind_along, 4.0))
        need_a = self.routes[1].need_wh(wind_along, self.rain) * (1.0 - self.progress)
        need_b = self.routes[2].need_wh(wind_along, self.rain) * (1.0 - self.progress)
        need_cur_disp = 3.0 if self.blocked else min(need_cur / rem_wh, 3.0)
        feats = [
            self.progress,
            self.battery,
            wind_along / 10.0,
            abs(wind_cross) / 10.0,
            need_cur_disp,
            min(need_a / rem_wh, 3.0),
            min(need_b / rem_wh, 3.0),
            min(r.clearance_m / 100.0, 5.0),
            min(self.routes[1].clearance_m / 100.0, 5.0),
            max(-1.0, min(self._retreat_margin(), 1.0)),
            self.switches / 3.0,
        ]
        return {"feats": feats, "done": self.done,
                "battery": self.battery, "progress": self.progress,
                "route": r.name, "retreat_lost": self.retreat_lost}

    @property
    def feature_dim(self) -> int:
        return 11

    # ------------------------------------------------------------ 步进
    def step(self, action: int) -> Tuple[Dict, float, bool, Dict]:
        if self.done:
            return self._state(), 0.0, True, {}
        r = self.routes[self.cur]
        reward = -0.02
        info: Dict = {}

        # 突发事件
        if not self.event_fired and self.steps >= self.event_step:
            self.event_fired = True
            info["event"] = self.event_type
            if self.event_type == "block":
                self.blocked = True          # 当前航道临时禁飞
            elif self.event_type == "gust":
                self.wind_speed = min(20.0, self.wind_speed + 9.0)
            else:
                self.rain += 7.0

        # 禁飞航道还硬飞 → 重罚并终止
        if self.blocked and action == 0:
            self.done = True
            reward -= 100.0
            info["end"] = "flew_into_no_fly"
            return self._state(), reward, True, info

        if action == 3:                     # 就近备降
            self.done = True
            # 备降：安全但不算完成任务，扣分体现"没送到"
            reward += -2.0 if self._retreat_margin() > 0 else -50.0
            info["end"] = "divert"
            return self._state(), reward, True, info

        if action in (1, 2):
            target = self.routes[action]
            wind_along, _ = self._wind_components()
            need = target.need_wh(wind_along, self.rain) * (1.0 - self.progress)
            if need > self.battery * BATTERY_WH:      # 该航道飞不到
                reward -= 50.0
                info["invalid_switch"] = True
            else:
                reward -= 1.0 * self.progress          # 越晚改越贵
                self.cur = action
                self.switches += 1
                self.blocked = False
                info["switched"] = target.name

        # 推进
        r = self.routes[self.cur]
        wind_along, wind_cross = self._wind_components()
        ground = max(CRUISE_SPEED + wind_along, 4.0)
        seg_km = min(ground * DT / 1000.0, r.length_m * (1.0 - self.progress) / 1000.0)
        if seg_km <= 1e-6:
            self.progress = 1.0
        else:
            self.progress = min(1.0, self.progress + seg_km / (r.length_m / 1000.0))
        cost = BASE_WH_PER_KM * seg_km * (1.0 + 0.12 * min(self.rain / 10.0, 1.5))
        self.battery -= cost / BATTERY_WH
        self.steps += 1

        # 风缓慢变化
        self.wind_dir = (self.wind_dir + self.rng.uniform(-12, 12)) % 360.0
        self.wind_speed = max(0.0, min(20.0, self.wind_speed + self.rng.uniform(-1.5, 1.5)))

        # 退路丢失（一次性重罚）
        if not self.retreat_lost and self._retreat_margin() < 0:
            self.retreat_lost = True
            reward -= 30.0
            info["retreat_lost"] = True

        # 终止条件
        if self.battery <= 0:
            self.done = True
            reward -= 100.0
            info["end"] = "battery_depleted"
        elif self.progress >= 1.0:
            self.done = True
            reward += 10.0 + 12.0 * max(0.0, self.battery)   # 抵达：固定奖励 + 省电奖励
            info["end"] = "arrived"
        elif self.steps >= self.max_steps:
            self.done = True
            info["end"] = "timeout"

        info["battery"] = round(self.battery, 4)
        self.ep_return += reward
        return self._state(), reward, self.done, info


# ------------------------------------------------------------------ 基线策略
def policy_always_continue(state: Dict, env: "RouteEnv") -> int:
    return 0


def policy_greedy(state: Dict, env: "RouteEnv") -> int:
    """规则基线：当前航道飞不到就换能飞且余度最大的；退路要丢了就备降。"""
    f = state["feats"]
    if f[9] < 0.02:                       # 退路快没了
        return 3
    if f[4] > 0.95:                       # 当前航道电量不够
        cands = [(f[5], 1), (f[6], 2)]
        cands = [c for c in cands if c[0] < 0.95]
        if cands:
            return min(cands)[1]
        return 3
    return 0
