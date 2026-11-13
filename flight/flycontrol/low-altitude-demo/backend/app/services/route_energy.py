# -*- coding: utf-8 -*-
"""航道的「安全可达性」评估：能不能安全飞到，而不只是能不能飞到。

三层约束
--------
    L1 安全：超障余度 ≥ MOC、不穿越限飞区、侧风在包线内
    L2 能量：全程能耗 ≤ 剩余电量 ×(1−安全余量)
    L3 退路：沿航道**每一点**都要能飞到最近备降点（ETOPS 思想）

为什么 L3 单独列
----------------
    一条航道总能耗刚好够、但中间一段前后都是障碍、最近备降点在 2 km 外，
    这条航道就不能飞——哪怕算下来电量够。真实运营里这叫"退路丢失"。

能量模型（演示级，参数集中在本文件顶部，便于替换成机型实测数据）
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

# ---- 机型/电池参数（演示值，接真实机型时替换这里即可）----
CRUISE_POWER_W = 3000.0      # 巡航功率
CLIMB_EFFICIENCY = 0.65      # 爬升效率
MASS_KG = 220.0
G = 9.81
BATTERY_WH = 1200.0          # 满电容量（Wh，小型 eVTOL 量级；巡航 3 kW × 2.5 km ≈ 380 Wh）
RESERVE_RATIO = 0.20         # 法规/公司安全余量
CROSSWIND_LIMIT = 12.0       # 侧风上限 m/s（机型包线，可按机型配置）
DEFAULT_SPEED = 15.0         # 无航路点速度时的默认空速 m/s


def _wh_per_meter(vz: float) -> float:
    """每米水平航程的能耗（Wh/m），vz 为垂直速度 m/s（爬升为正）。"""
    return CRUISE_POWER_W / 3600.0 / DEFAULT_SPEED


def _leg_energy(a, b, wind_along: float) -> Tuple[float, float]:
    """单段能耗（Wh）与地速（m/s）。wind_along>0 表示顺风。"""
    dh = math.hypot(b.x - a.x, b.y - a.y)
    vz = (b.z - a.z) if dh < 1e-6 else (b.z - a.z)
    airspeed = max(getattr(a, "speed", 0.0) or DEFAULT_SPEED, 3.0)
    ground = max(airspeed + wind_along, 2.0)          # 逆风地速下降
    t = dh / ground                                    # 秒

    pw = CRUISE_POWER_W
    if vz > 0:
        pw += MASS_KG * G * vz / max(CLIMB_EFFICIENCY, 0.1)
    elif vz < 0:
        pw *= 0.75                                     # 下降省电
    return pw * t / 3600.0, ground


def assess_route(prog, env, battery_pct: float = 100.0,
                 reserve: float = RESERVE_RATIO,
                 sample_step: float = 50.0) -> Dict:
    """逐点扫描一条航道，返回分段结论与总体判定。"""
    wps = list(getattr(prog, "waypoints", []) or [])
    if len(wps) < 2:
        return {"verdict": "EMPTY", "ok": False, "segments": [],
                "reasons": ["没有可用航路点"], "metrics": {}}

    wind = env.meteo
    precip = float(getattr(wind, "precipitation", 0.0) or 0.0)
    rain_factor = 1.0 + 0.12 * min(precip / 10.0, 1.5)     # 降水增加功率
    wind_speed = float(getattr(wind, "wind_speed", 0.0) or 0.0)
    wind_dir = float(getattr(wind, "wind_dir", 0.0) or 0.0)

    remaining_wh = BATTERY_WH * max(0.0, min(100.0, battery_pct)) / 100.0
    need_wh = 0.0
    segments: List[dict] = []
    worst_clear = 1e9
    bad_airspace = None
    worst_xwind = 0.0

    for a, b in zip(wps, wps[1:]):
        dh = math.hypot(b.x - a.x, b.y - a.y)
        if dh < 1e-6:
            continue
        # 航段方位（0=北），风沿航段的分量：顺风为正
        hdg = math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360.0
        delta = math.radians((wind_dir - hdg + 180.0) % 360.0 - 180.0)
        wind_along = wind_speed * math.cos(delta)
        xwind = abs(wind_speed * math.sin(delta))
        worst_xwind = max(worst_xwind, xwind)

        n = max(1, int(dh / sample_step))
        for i in range(n + 1):
            t = i / n
            px = a.x + (b.x - a.x) * t
            py = a.y + (b.y - a.y) * t
            pz = a.z + (b.z - a.z) * t

            # L1-a 超障：**垂直**余度（水平进入障碍物投影范围才算）
            # 之前误用"水平距离 − 半径"，把 75 m 的 MOC 当成水平间距，
            # 导致离塔吊还有 40 m 的航迹被判成"撞障碍"（S 方向被误杀）
            clear = 1e9
            for o in (env.obstacles or []):
                rad = float(getattr(o, "radius", 0) or getattr(o, "inflated_radius", 20) or 20)
                if math.hypot(px - o.x, py - o.y) <= rad:
                    top = float(getattr(o, "top_agl", getattr(o, "height_msl", 0)) or 0)
                    clear = min(clear, pz - top)
            if clear < 1e8:
                worst_clear = min(worst_clear, clear)

            # L1-b 空域
            inside = False
            for a_ in (env.airspaces or []):
                if a_.floor_agl <= pz <= a_.ceiling_agl and _in_poly(px, py, a_.polygon):
                    inside = True
                    bad_airspace = a_.name
                    break

            # L2 已消耗
            if i > 0:
                e, _ = _leg_energy(_P(px, py, pz, a.speed), _P(px, py, pz, a.speed), wind_along)
                # 用采样段长度估算
            need_wh += (CRUISE_POWER_W / 3600.0 / DEFAULT_SPEED) * (dh / n) * \
                       (DEFAULT_SPEED / max(DEFAULT_SPEED + wind_along, 2.0))

            ok_energy = need_wh <= remaining_wh * (1.0 - reserve)

            # L3 退路：从当前位置飞回最近备降点（这里取起降点）要多少电
            back = math.hypot(px, py)
            retreat_wh = (CRUISE_POWER_W / 3600.0 / DEFAULT_SPEED) * back
            ok_retreat = (need_wh + retreat_wh) <= remaining_wh * (1.0 - reserve)
            ok_safe = (clear >= float(getattr(getattr(env, "limits", None), "moc_approach", 75.0) or 75.0)
                       and not inside and xwind <= CROSSWIND_LIMIT)

            segments.append({
                "x": round(px, 1), "y": round(py, 1), "z": round(pz, 1),
                "clearance": round(clear, 1), "in_airspace": inside,
                "xwind": round(xwind, 1),
                "energy_used": round(need_wh, 1),
                "ok_retreat": bool(ok_retreat),
                "retreat_wh": round(retreat_wh, 1),
                "ok": bool(ok_safe and ok_energy and ok_retreat),
                "level": "red" if not (ok_safe and ok_energy) else
                         ("yellow" if need_wh > remaining_wh * (1.0 - reserve - 0.10) else "green"),
            })

    lost_retreat = [g for g in segments if not g["ok_retreat"]]
    safe = bad_airspace is None and worst_clear >= 75.0 and worst_xwind <= CROSSWIND_LIMIT
    energy_ok = need_wh <= remaining_wh * (1.0 - reserve)
    margin = (remaining_wh * (1.0 - reserve) - need_wh) / max(remaining_wh, 1.0)

    if not safe:
        verdict, ok = "UNSAFE", False
    elif lost_retreat:
        verdict, ok = "NO_RETREAT", False
    elif not energy_ok:
        verdict, ok = "ENERGY_SHORT", False
    elif margin < 0.10:
        verdict, ok = "TIGHT", True
    else:
        verdict, ok = "OK", True

    reasons = []
    if bad_airspace:
        reasons.append("穿越限制空域[%s]" % bad_airspace)
    if worst_clear < 75.0:
        reasons.append("最小超障余度 %.0f m < 75 m" % worst_clear)
    if worst_xwind > CROSSWIND_LIMIT:
        reasons.append("最大侧风 %.1f m/s 超包线" % worst_xwind)
    if lost_retreat:
        g = lost_retreat[0]
        reasons.append("退路丢失：在 (%.0f, %.0f) 处已无法飞回备降点" % (g["x"], g["y"]))
    reasons.append("能耗 %.0f Wh / 可用 %.0f Wh（余量 %.0f%%）"
                   % (need_wh, remaining_wh, max(0.0, margin * 100)))

    return {
        "verdict": verdict, "ok": ok,
        "segments": segments,
        "reasons": reasons,
        "metrics": {"need_wh": round(need_wh, 1),
                    "available_wh": round(remaining_wh, 1),
                    "margin": round(margin, 3),
                    "min_clearance": None if worst_clear > 1e8 else round(worst_clear, 1),
                    "max_xwind": round(worst_xwind, 1)},
    }


class _P:
    __slots__ = ("x", "y", "z", "speed")

    def __init__(self, x, y, z, speed):
        self.x, self.y, self.z, self.speed = x, y, z, speed


def _in_poly(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            t = (y - yi) / (yj - yi) if abs(yj - yi) > 1e-12 else 0.0
            if x < xi + t * (xj - xi):
                inside = not inside
        j = i
    return inside
