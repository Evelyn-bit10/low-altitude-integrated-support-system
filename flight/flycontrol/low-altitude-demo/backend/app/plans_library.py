# -*- coding: utf-8 -*-
"""进出场程序方案库（8 个方向 × 进近/离场）。

设计
----
- 方向 `direction` 表示「从哪个方向来 / 往哪个方向去」，取值 N/NE/E/SE/S/SW/W/NW，
  方位角以真北为 0、顺时针。
- 进场：飞机从该方向的 2500 m 处进入，反向着陆（着陆航向 = 方位角 + 180°）。
- 离场：起飞后朝该方向爬升，3000 m 处到达 300 m。
- 模板航路点为相对起降点的本地 ENU（x 东 / y 北 / z 相对标高），
  与 `shared/contract.md` 的坐标约定一致；对外输出时由接口层转成经纬度。

模板只用于「方案库直出」，当环境变化（障碍物/气象）时仍走 planner 动态重规划。
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .domain import Waypoint
from .engines.geometry import dist3d
from .engines.planner import DIRECTIONS, DIRECTION_CN, bearing_of, direction_name

__all__ = ["DIRECTIONS", "DIRECTION_CN", "build_library", "find_plans", "plan_to_program"]

# 进近剖面: (距起降点水平距离 m, 高度 AGL m, 速度 m/s)
_ARRIVAL_PROFILE = [(2500.0, 250.0, 25.0), (1500.0, 150.0, 22.0),
                    (800.0, 80.0, 18.0), (0.0, 0.0, 10.0)]
# 离场剖面
_DEPARTURE_PROFILE = [(0.0, 0.0, 10.0), (600.0, 60.0, 16.0),
                      (1500.0, 150.0, 22.0), (3000.0, 300.0, 26.0)]


def _waypoints_for(bearing: float, profile) -> List[Dict[str, float]]:
    """按方位角把「距离-高度」剖面铺成 ENU 航路点。"""
    ux, uy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
    out = []
    for dist, alt, spd in profile:
        out.append({"x": round(ux * dist, 1), "y": round(uy * dist, 1),
                    "z": round(alt, 1), "speed": spd})
    return out


def _length_m(wps: List[Dict[str, float]]) -> float:
    total = 0.0
    for a, b in zip(wps, wps[1:]):
        total += dist3d((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
    return round(total, 1)


def build_library(point_code: str = "LAC-DEMO") -> List[dict]:
    """生成 16 条方案（8 方向 × 2 类型）。"""
    plans: List[dict] = []
    for idx, (name, bearing) in enumerate(DIRECTIONS.items()):
        cn = DIRECTION_CN[name]

        # ---- 进近 ----
        wps = _waypoints_for(bearing, _ARRIVAL_PROFILE)
        plans.append({
            "id": 100 + idx,
            "point_code": point_code,
            "plan_name": "%s向进近（%s）" % (cn, name),
            "plan_type": 1,                       # 1=arrival（与 lp_program_plan 一致）
            "direction": name,
            "entry_bearing": bearing,             # 入口方位角
            "exit_bearing": (bearing + 180) % 360,
            "std_name": "ARR-%s" % name,
            "waypoints": wps,
            "length_m": _length_m(wps),
            "min_vis": 1600,
            "max_wind": 12.0,
            "wind_range": "0-12",
            "visi_range": "1600-99999",
            # 跑道朝北（0°）时，默认进近来自南方
            "is_default": 1 if name == direction_name(180.0) else 0,
            "source": "library",
        })

        # ---- 离场 ----
        wps = _waypoints_for(bearing, _DEPARTURE_PROFILE)
        plans.append({
            "id": 200 + idx,
            "point_code": point_code,
            "plan_name": "%s向离场（%s）" % (cn, name),
            "plan_type": 2,                       # 2=departure
            "direction": name,
            "entry_bearing": (bearing + 180) % 360,
            "exit_bearing": bearing,
            "std_name": "DEP-%s" % name,
            "waypoints": wps,
            "length_m": _length_m(wps),
            "min_vis": 1200,
            "max_wind": 14.0,
            "wind_range": "0-14",
            "visi_range": "1200-99999",
            "is_default": 1 if name == direction_name(0.0) else 0,
            "source": "library",
        })
    return plans


def find_plans(plans: List[dict], program_type: str,
               direction: Optional[str] = None) -> List[dict]:
    """按类型 / 方向筛选方案。"""
    want = 1 if program_type == "arrival" else 2
    out = [p for p in plans if int(p.get("plan_type") or 0) == want]
    if direction:
        b = bearing_of(direction)
        if b is not None:
            key = direction_name(b)
            out = [p for p in out if p.get("direction") == key]
    # 默认方案排前面
    out.sort(key=lambda p: (0 if p.get("is_default") else 1, p.get("id", 0)))
    return out


def plan_to_program(plan: dict, program_type: str, env=None):
    """把方案字典转成 FlightProgram（模板直出）。"""
    from .domain import FlightProgram

    wps = [Waypoint(float(w["x"]), float(w["y"]), float(w["z"]),
                    speed=float(w.get("speed", 0.0)))
           for w in plan.get("waypoints", [])]
    prog = FlightProgram(program_type, wps, source="plan",
                         plan_id=int(plan.get("id", 0)),
                         direction=plan.get("direction"),
                         std_name=plan.get("std_name"))
    # 模板方案也带一条复飞航路；有环境快照时用"会避障/避限飞区"的规划器版本
    bearing = float(plan.get("exit_bearing", 0.0))
    if env is not None:
        try:
            from app.engines import planner as _planner
            msa = _planner.calc_msa(env.obstacles, 300.0)
            prog.miss_approach = _planner.build_missed_approach(
                (0.0, 0.0, 0.0), bearing, msa, env.limits,
                obstacles=env.obstacles, airspaces=getattr(env, "airspaces", None))
        except Exception:      # 规划器不可用时退回简化版，绝不影响主流程
            prog.miss_approach = _missed_approach(bearing)
    else:
        prog.miss_approach = _missed_approach(bearing)
    return prog


def _missed_approach(bearing: float) -> List[Waypoint]:
    """简化复飞：沿 bearing 直线爬升至 300 m。"""
    ux, uy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
    return [Waypoint(0.0, 0.0, 0.0),
            Waypoint(ux * 500.0, uy * 500.0, 50.0),
            Waypoint(ux * 1200.0, uy * 1200.0, 120.0),
            Waypoint(ux * 2000.0, uy * 2000.0, 200.0),
            Waypoint(ux * 2800.0, uy * 2800.0, 300.0)]
