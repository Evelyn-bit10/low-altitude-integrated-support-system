# -*- coding: utf-8 -*-
"""去重关联的仿真数据生成器（带真值）。

用途：为「学习式关联」提供带标签的训练/测试数据，并复现现有规则引擎的输入形态。

设计：
  - N 架飞机（真值身份 = UA-xxxx），在平面内按速度/航向运动，可转弯；
  - 两个观测源（模拟 RID / ADS-B），各有不同的位置噪声、探测率、ID 携带率；
  - 输出「帧」：每帧包含各源的观测（带真值 ID）+ 上一帧融合出的航迹状态；
  - 配对样本 = (观测, 候选航迹) -> label = 1 表示同一架。

不依赖 app/，参数与生产默认值保持一致（dedup.py）。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---- 与 app/services/dedup.py 保持一致 ----
V_MAX = 30.0
SIGMA_M = 15.0
GATE_SIGMA = 3.0
ALT_GATE = 30.0
HEADING_GATE = 30.0

M_PER_DEG_LAT = 111320.0


@dataclass
class Source:
    name: str
    sigma: float          # 位置噪声标准差（米）
    p_detect: float       # 每帧探测概率
    p_id: float           # 携带 ua_id 的概率
    quality: float        # 上报质量（0~1）
    bias: Tuple[float, float] = (0.0, 0.0)   # 系统性偏差（米），模拟标定误差


SOURCES = [
    Source("A-RID", sigma=8.0, p_detect=0.96, p_id=0.95, quality=0.8),
    Source("B-RID", sigma=22.0, p_detect=0.86, p_id=0.55, quality=0.6),
]

# 困难场景：噪声大、B 有系统性偏差、ID 携带率低、目标更密集
HARD_SOURCES = [
    Source("A-RID", sigma=15.0, p_detect=0.95, p_id=0.90, quality=0.8),
    Source("B-RID", sigma=45.0, p_detect=0.80, p_id=0.35, quality=0.6, bias=(25.0, -15.0)),
]

# 极端场景：目标间距与观测噪声同量级（真正难判的情形）
EXTREME_SOURCES = [
    Source("A-RID", sigma=20.0, p_detect=0.95, p_id=0.90, quality=0.8),
    Source("B-RID", sigma=60.0, p_detect=0.85, p_id=0.20, quality=0.6, bias=(30.0, -20.0)),
]

# 无 ID 场景：完全靠几何匹配（用来检验纯几何能力）
NOID_SOURCES = [
    Source("A-RID", sigma=12.0, p_detect=0.95, p_id=0.0, quality=0.8),
    Source("B-RID", sigma=35.0, p_detect=0.85, p_id=0.0, quality=0.6, bias=(12.0, -8.0)),
]

LEVELS = {"easy": SOURCES, "hard": HARD_SOURCES,
          "extreme": EXTREME_SOURCES, "noid": NOID_SOURCES}


@dataclass
class Aircraft:
    idx: int
    x: float
    y: float
    z: float
    heading: float        # 度
    speed: float          # m/s
    turn: float           # 每秒转向（度），0 表示直飞

    @property
    def ua_id(self) -> str:
        return "UA-%04d" % self.idx

    @property
    def reg_no(self) -> str:
        return "REG-%04d" % self.idx

    def step(self, dt: float = 1.0):
        self.heading = (self.heading + self.turn * dt) % 360.0
        rad = math.radians(self.heading)
        self.x += math.sin(rad) * self.speed * dt
        self.y += math.cos(rad) * self.speed * dt


@dataclass
class Observation:
    src: str
    x: float
    y: float
    z: float
    heading: float
    speed: float
    ua_id: Optional[str]
    reg_no: Optional[str]
    quality: float
    sigma: float
    truth: int            # 真值身份（仅仿真用，不参与特征）


@dataclass
class TrackState:
    truth: int
    x: float
    y: float
    z: float
    heading: float
    speed: float
    ua_id: Optional[str]
    reg_no: Optional[str]
    last_t: float
    seen: int = 0


def make_aircraft(n: int, scenario: str, rng: random.Random) -> List[Aircraft]:
    planes: List[Aircraft] = []
    for i in range(n):
        if scenario == "sparse":
            x = rng.uniform(-1500, 1500)
            y = rng.uniform(-1000, 1000)
            hdg = rng.uniform(0, 360)
        elif scenario == "dense":
            x = rng.uniform(-400, 400)
            y = rng.uniform(-300, 300)
            hdg = rng.uniform(0, 360)
        elif scenario == "hard_dense":
            x = rng.uniform(-125, 125)
            y = rng.uniform(-90, 90)
            hdg = rng.uniform(0, 360)
        elif scenario == "swarm":
            # 12 架同向同速、挤在 40x40 m 内：只能靠几何区分
            x = rng.uniform(-20, 20)
            y = rng.uniform(-20, 20)
            hdg = 90.0
        elif scenario == "orbit":
            # 盘旋：半径约 70 m、速度 22 m/s，向心加速度 ≈ 7 m/s²。
            # 演示台的真实数据就是这种形态，卡尔曼的匀速模型在这里最吃力。
            ang = 2 * math.pi * i / max(1, n)
            x = 900 * math.cos(ang)
            y = 900 * math.sin(ang)
            hdg = (math.degrees(ang) + 90.0) % 360.0
            plane = Aircraft(i, x, y, 120.0, hdg, 22.0, 6.0 if i % 2 == 0 else -6.0)
            planes.append(plane)
            continue
        elif scenario == "extreme_dense":
            # 12 架挤在 70x50 m 内：间距 ≈ 观测噪声，最近邻不再可靠
            x = rng.uniform(-35, 35)
            y = rng.uniform(-25, 25)
            hdg = rng.uniform(0, 360)
        elif scenario == "cross":
            # 全部朝中心飞，制造交叉
            ang = 2 * math.pi * i / n
            x, y = math.sin(ang) * rng.uniform(700, 900), math.cos(ang) * rng.uniform(700, 900)
            hdg = (math.degrees(ang) + 180.0) % 360.0
        elif scenario in ("formation", "hard_formation"):
            tight = scenario == "hard_formation"
            # 4 组编队，组内间距 25~40 m，同向飞行
            g = i // 3
            ang = 2 * math.pi * g / max(1, (n + 2) // 3)
            base_x, base_y = math.sin(ang) * 900, math.cos(ang) * 900
            spread = 12 if tight else 35
            x = base_x + rng.uniform(-spread, spread)
            y = base_y + rng.uniform(-spread, spread)
            hdg = (math.degrees(ang) + 180.0) % 360.0
        else:
            raise ValueError(scenario)
        if scenario == "swarm":
            z, spd, turn = 120.0, 12.0, 0.0
        else:
            z, spd, turn = rng.uniform(60, 200), rng.uniform(8, 20),                 rng.choice([0.0, 0.0, 0.0, 2.0, -2.0])
        planes.append(Aircraft(idx=i, x=x, y=y, z=z, heading=hdg,
                               speed=spd, turn=turn))
    return planes


def sample(plane: Aircraft, src: Source, rng: random.Random, t: float) -> Optional[Observation]:
    if rng.random() > src.p_detect:
        return None
    has_id = rng.random() < src.p_id
    return Observation(
        src=src.name,
        x=plane.x + src.bias[0] + rng.gauss(0, src.sigma),
        y=plane.y + src.bias[1] + rng.gauss(0, src.sigma),
        z=plane.z + rng.gauss(0, 3.0),
        heading=(plane.heading + rng.gauss(0, 3.0)) % 360.0,
        speed=max(0.0, plane.speed + rng.gauss(0, 0.8)),
        ua_id=plane.ua_id if has_id else None,
        reg_no=plane.reg_no if has_id else None,
        quality=src.quality,
        sigma=src.sigma,
        truth=plane.idx,
    )


def update_tracks(obs: List[Observation], prev: Dict[int, TrackState], t: float):
    """按真值身份把本帧观测做逆方差加权，得到下一帧的候选航迹。"""
    buckets: Dict[int, List[Observation]] = {}
    for o in obs:
        buckets.setdefault(o.truth, []).append(o)

    tracks: Dict[int, TrackState] = dict(prev)
    for truth, items in buckets.items():
        wsum = sum(1.0 / (o.sigma ** 2) for o in items)
        x = sum(o.x / (o.sigma ** 2) for o in items) / wsum
        y = sum(o.y / (o.sigma ** 2) for o in items) / wsum
        z = sum(o.z / (o.sigma ** 2) for o in items) / wsum
        hd = sum(o.heading / (o.sigma ** 2) for o in items) / wsum
        sp = sum(o.speed / (o.sigma ** 2) for o in items) / wsum
        ua = next((o.ua_id for o in items if o.ua_id), None)
        reg = next((o.reg_no for o in items if o.reg_no), None)
        old = tracks.get(truth)
        tracks[truth] = TrackState(truth=truth, x=x, y=y, z=z, heading=hd,
                                   speed=sp,
                                   ua_id=ua or (old.ua_id if old else None),
                                   reg_no=reg or (old.reg_no if old else None),
                                   last_t=t, seen=(old.seen + 1 if old else 1))
    return tracks


def angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def generate(scenario: str, n_planes: int = 12, frames: int = 150,
             seed: int = 0, level: str = "easy") -> List[dict]:
    """生成一个场景的逐帧数据。

    每帧返回：
        {"t":..., "obs":[...], "tracks":[TrackState...]}
    其中 `tracks` 是**上一帧**留下的候选航迹（供本帧匹配）。
    """
    rng = random.Random(seed)
    sources = LEVELS[level]
    planes = make_aircraft(n_planes, scenario, rng)
    tracks: Dict[int, TrackState] = {}
    out = []

    for k in range(frames):
        t = float(k)
        obs: List[Observation] = []
        for plane in planes:
            for src in sources:
                o = sample(plane, src, rng, t)
                if o:
                    obs.append(o)

        if tracks:
            out.append({"t": t, "obs": obs, "tracks": list(tracks.values()),
                        "n_truth": len(planes)})
        tracks = update_tracks(obs, tracks, t)
        for plane in planes:
            plane.step(1.0)
    return out


def pair_features(o: Observation, tr: TrackState, t: float,
                  rank: int) -> Tuple[List[float], int, float]:
    """构造一对 (观测, 航迹) 的特征；返回 (features, label, rule_score)。"""
    dt = max(0.0, t - tr.last_t)
    d = math.hypot(o.x - tr.x, o.y - tr.y)
    gate = V_MAX * dt + GATE_SIGMA * o.sigma
    d_over_gate = d / gate if gate > 0 else 99.0
    d_alt = abs(o.z - tr.z)
    d_hdg = angle_diff(o.heading, tr.heading)
    d_spd = abs(o.speed - tr.speed)

    ua_same = 1.0 if (o.ua_id and tr.ua_id and o.ua_id == tr.ua_id) else 0.0
    ua_conflict = 1.0 if (o.ua_id and tr.ua_id and o.ua_id != tr.ua_id) else 0.0
    ua_missing = 1.0 if (o.ua_id is None or tr.ua_id is None) else 0.0
    reg_same = 1.0 if (o.reg_no and tr.reg_no and o.reg_no == tr.reg_no) else 0.0
    reg_conflict = 1.0 if (o.reg_no and tr.reg_no and o.reg_no != tr.reg_no) else 0.0

    speed_rel = d_spd / max(1.0, tr.speed)
    slow = 1.0 if min(o.speed, tr.speed) < 2.0 else 0.0

    feats = [
        min(d_over_gate, 5.0),      # 归一化距离（最关键）
        d / 100.0,                  # 绝对距离（百米）
        d_alt / 30.0,               # 归一化高差
        d_hdg / 30.0,               # 归一化航向差
        dt,
        ua_same, ua_conflict, ua_missing,
        reg_same, reg_conflict,
        speed_rel,
        float(rank),                # 本观测的候选里按距离的排名
        float(tr.seen),             # 该航迹已连续跟踪的帧数
        o.quality,
        o.sigma / 20.0,
        slow,
    ]

    # 规则引擎的连续打分（与 dedup.py 的 _geo_score 一致）
    if ua_conflict or reg_conflict:
        rule = 0.0
    elif d > gate or d_alt > ALT_GATE:
        rule = 0.0
    elif (not slow) and d_hdg > HEADING_GATE:
        rule = 0.0
    else:
        rule = max(0.0, 1.0 - d / max(gate, 1e-6))

    label = 1 if o.truth == tr.truth else 0
    return feats, label, rule


FEATURE_NAMES = [
    "距离/门限", "绝对距离", "高差/30m", "航向差/30°", "Δt",
    "ua相同", "ua冲突", "ua缺失",
    "reg相同", "reg冲突",
    "速度相对差", "候选排名", "航迹已跟踪帧数",
    "源质量", "源σ/20", "低速标志",
]
