"""引擎 4: 航迹仿真验证引擎(最小可运行实现)。

对规划结果做三项仿真级校验(对应原伪代码 SimulateCheck):
  1. 障碍物碰撞(沿航迹采样 + 圆柱膨胀)
  2. 气象适配(侧风/能见度/湍流/风切变 vs 机型包线)
  3. 空域冲突(航迹点 vs 限飞多边形 + 高度层)
"""
from __future__ import annotations

import math

from dataclasses import dataclass, field
from typing import List

from ..domain import EnvSnapshot, FlightProgram
from . import geometry as geo


@dataclass
class SimulateResult:
    passed: bool
    checks: List[dict] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return self.passed

    def err_msg(self) -> str:
        return "; ".join(c["msg"] for c in self.checks if not c["pass"])


def _paths(program: FlightProgram):
    """主航迹和复飞段是**两条独立航路**，必须分开检查。

    （踩过的坑：拼成一个列表会凭空多出一段"末点→复飞起点"的直线，
      把所有方向都判成撞障碍。）
    """
    out = []
    for seq in (program.waypoints, program.miss_approach or []):
        pts = [(w.x, w.y, w.z) for w in (seq or [])]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _sample_segment(a, b, step: float = 50.0):
    d = math.dist(a, b) if hasattr(math, "dist") else (
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
    n = max(1, int(d / step))
    for i in range(n + 1):
        t = i / n
        yield (a[0] + (b[0] - a[0]) * t,
               a[1] + (b[1] - a[1]) * t,
               a[2] + (b[2] - a[2]) * t)


def check_collision(program: FlightProgram, obstacles, clearance: float = 10.0) -> dict:
    for pts in _paths(program):
        for i in range(len(pts) - 1):
            if not geo.segment_free(pts[i], pts[i + 1], obstacles, clearance):
                return {"name": "障碍物碰撞", "pass": False, "msg": "航迹存在障碍物碰撞风险"}
    return {"name": "障碍物碰撞", "pass": True, "msg": "航迹无障碍物碰撞"}


def check_meteo_fit(program: FlightProgram, meteo, limits) -> dict:
    precip = float(getattr(meteo, "precipitation", 0.0) or 0.0)
    if precip >= 10.0:
        return {"name": "气象适配", "pass": False,
                "msg": f"降水 {precip:.1f} mm/h（大雨），超出运行限制"}
    if precip >= 4.0 and float(getattr(meteo, "visibility", 8000)) < 3000:
        return {"name": "气象适配", "pass": False,
                "msg": f"中雨 {precip:.1f} mm/h 且能见度不足"}
    if meteo.wind_speed > limits.max_crosswind:
        return {"name": "气象适配", "pass": False,
                "msg": f"风速 {meteo.wind_speed:.0f}m/s 超机型侧风限制 {limits.max_crosswind:.0f}m/s"}
    if meteo.visibility < 500:
        return {"name": "气象适配", "pass": False,
                "msg": f"能见度 {meteo.visibility:.0f}m 低于运行最低标准"}
    if meteo.turbulence >= 4:
        return {"name": "气象适配", "pass": False, "msg": "湍流等级过高, 禁止运行"}
    if meteo.wind_shear >= 4:
        return {"name": "气象适配", "pass": False, "msg": "风切变等级过高, 禁止运行"}
    return {"name": "气象适配", "pass": True, "msg": "当前气象满足航迹运行约束"}


def check_airspace_conflict(program: FlightProgram, airspaces) -> dict:
    # 航段要逐点采样：只有 4~5 个航路点时，整段切进限飞区也可能一个点都不落在里面
    samples = []
    for pts in _paths(program):
        for a, b in zip(pts, pts[1:]):
            samples.extend(_sample_segment(a, b))
        samples.extend(pts)
    for a in airspaces or ():
        for x, y, z in samples:
            if a.floor_agl <= z <= a.ceiling_agl and geo.point_in_polygon(x, y, a.polygon):
                return {"name": "空域冲突", "pass": False,
                        "msg": f"航迹侵入限制空域[{a.name}]"}
    return {"name": "空域冲突", "pass": True, "msg": "航迹未侵入限制空域"}


def simulate_check(program: FlightProgram, env: EnvSnapshot) -> SimulateResult:
    checks = [
        check_collision(program, env.obstacles),
        check_meteo_fit(program, env.meteo, env.limits),
        check_airspace_conflict(program, env.airspaces),
    ]
    return SimulateResult(all(c["pass"] for c in checks), checks)
