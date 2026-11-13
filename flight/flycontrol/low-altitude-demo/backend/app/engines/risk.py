"""引擎 2: 低空环境风险评估引擎(多因子加权模型)。

采用透明加权打分模型(障碍物 / 气象 / 空域), 权重与阈值来自规则库 lp_avi_rule,
可在运行时配置。对应原伪代码 EnvRiskAssess 的评分 -> 分级逻辑:
    总分 <= 20 : 低风险  (SAFE)
    总分 <= 40 : 中风险  (NORMAL)
    总分 <= 70 : 高风险  (WARNING, 需调整程序)
    总分 >  70 : 禁飞级  (FORBID)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..domain import Airspace, EnvSnapshot, FlightProgram, Obstacle
from . import geometry as geo

SAFE = 1
NORMAL = 2
WARNING = 3
FORBID = 4

LEVEL_NAMES = {SAFE: "低风险", NORMAL: "中风险", WARNING: "高风险", FORBID: "禁飞级"}


@dataclass
class RiskResult:
    score: float
    level: int
    level_name: str
    factors: Dict[str, float] = field(default_factory=dict)
    program_status: str = "STATIC_VALID"   # STATIC_VALID / NEED_ADJUST / INVALID
    matched_plan_id: Optional[int] = None

    def needs_adjust(self) -> bool:
        return self.program_status == "NEED_ADJUST"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def obstacle_clearance(program: Optional[FlightProgram], obstacles: List[Obstacle]) -> float:
    """航迹相对其水平保护区内障碍物顶部的最小垂直净空(m)。

    返回 +inf 表示无障碍物落在航迹保护区内; 返回 -inf 表示无程序(最坏情况)。
    """
    if program is None or not program.waypoints:
        return -math.inf
    best = math.inf
    for w in program.waypoints:
        for o in obstacles:
            if geo.dist2d((w.x, w.y), (o.x, o.y)) <= o.inflated_radius:
                best = min(best, w.z - o.top_agl)
    return best


def obstacle_risk(program: Optional[FlightProgram], obstacles: List[Obstacle], moc: float) -> float:
    """障碍物软风险(0~100): 净空 >= MOC 记 0 分, 净空 <= 0 记 100 分。"""
    if not obstacles:
        return 0.0
    if program is None or not program.waypoints:
        # 无程序时按最高障碍物保守估计
        return _clamp(100.0 * (max(o.top_agl for o in obstacles) / (moc * 3)))
    cl = obstacle_clearance(program, obstacles)
    if cl == math.inf:
        return 0.0
    return _clamp(100.0 * (1.0 - cl / moc))


def meteo_risk(meteo, limits) -> float:
    """气象风险: 能见度 / 风切变 / 湍流 / 阵风 / 侧风 综合 0~100。"""
    s = 0.0
    # 能见度(米): <300 高分, >3000 低分
    if meteo.visibility < 300:
        s += 40
    elif meteo.visibility < 1000:
        s += 28
    elif meteo.visibility < 3000:
        s += 15
    # 风切变等级 1~4
    s += (meteo.wind_shear - 1) / 3.0 * 25
    # 湍流等级
    s += (meteo.turbulence - 1) / 3.0 * 15
    # 阵风 vs 风速(突变)
    if meteo.gust - meteo.wind_speed > 8:
        s += 12
    # 侧风 vs 机型限制
    if limits.max_crosswind > 0 and meteo.wind_speed > limits.max_crosswind:
        s += 15
    return _clamp(s)


def airspace_risk(program: Optional[FlightProgram], airspaces: List[Airspace]) -> float:
    """空域风险: 航迹进入限飞区记高分, 邻近记折算分。"""
    if not airspaces:
        return 0.0
    worst = 0.0
    pts = [(w.x, w.y, w.z) for w in program.waypoints] if program else []
    for a in airspaces:
        for (x, y, z) in pts:
            d = geo.poly_distance(x, y, a.polygon)
            if d == 0.0 and a.floor_agl <= z <= a.ceiling_agl:
                worst = max(worst, 100.0)
            else:
                worst = max(worst, _clamp(60.0 * (1.0 - d / 500.0)))
    return worst


def airspace_violation(program: Optional[FlightProgram], airspaces: List[Airspace]) -> Optional[str]:
    """硬空域冲突: 航迹点落在限飞区水平范围且高度层重叠时返回空域名。"""
    if not program or not airspaces:
        return None
    for a in airspaces:
        for w in program.waypoints:
            if a.floor_agl <= w.z <= a.ceiling_agl and geo.point_in_polygon(w.x, w.y, a.polygon):
                return a.name
    return None


def match_best_plan(env: EnvSnapshot, plans: List[dict]) -> Optional[int]:
    """预案匹配: 风速与能见度同时落在预案区间内则命中(取 is_default 优先)。"""
    ws = env.meteo.wind_speed
    vis = env.meteo.visibility
    candidates = []
    for p in plans:
        if not _in_range(ws, p.get("wind_range")):
            continue
        if not _in_range(vis, p.get("visi_range")):
            continue
        candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: 0 if p.get("is_default") else 1)
    return candidates[0].get("id")


def _in_range(v: float, spec: Optional[str]) -> bool:
    if not spec:
        return True
    try:
        lo_s, hi_s = spec.split("-")
        return float(lo_s) <= v <= float(hi_s)
    except Exception:
        return True


def assess(env: EnvSnapshot, current_program: Optional[FlightProgram],
           plans: List[dict], rules: dict) -> RiskResult:
    """多因子加权综合评估。"""
    w_obs = float(rules.get("RISK_W_OBSTACLE", 0.45))
    w_met = float(rules.get("RISK_W_METEO", 0.35))
    w_air = float(rules.get("RISK_W_AIRSPACE", 0.20))
    moc = float(rules.get("MOC_APPROACH", 75))

    f_obs = obstacle_risk(current_program, env.obstacles, moc)
    f_met = meteo_risk(env.meteo, env.limits)
    f_air = airspace_risk(current_program, env.airspaces)

    score = w_obs * f_obs + w_met * f_met + w_air * f_air
    score = round(score, 1)

    th_safe = float(rules.get("RISK_TH_SAFE", 20))
    th_normal = float(rules.get("RISK_TH_NORMAL", 40))
    th_warning = float(rules.get("RISK_TH_WARNING", 70))

    # 硬安全红线(独立于加权分, 直接升级)
    hard_forbid = False
    hard_adjust = False
    if airspace_violation(current_program, env.airspaces) is not None:
        hard_forbid = True
    if env.meteo.visibility < 500:
        hard_forbid = True
    if env.meteo.wind_speed > env.limits.max_crosswind:
        hard_forbid = True
    if (current_program is not None
            and obstacle_clearance(current_program, env.obstacles) < moc):
        hard_adjust = True

    if hard_forbid:
        level, status = FORBID, "INVALID"
    elif hard_adjust:
        level, status = WARNING, "NEED_ADJUST"
    elif score <= th_safe:
        level, status = SAFE, "STATIC_VALID"
    elif score <= th_normal:
        level, status = NORMAL, "STATIC_VALID"
    elif score <= th_warning:
        level, status = WARNING, "NEED_ADJUST"
    else:
        level, status = FORBID, "INVALID"

    matched = None
    if status == "NEED_ADJUST":
        matched = match_best_plan(env, plans)

    return RiskResult(
        score=score, level=level, level_name=LEVEL_NAMES[level],
        factors={"obstacle": round(f_obs, 1), "meteo": round(f_met, 1),
                 "airspace": round(f_air, 1)},
        program_status=status, matched_plan_id=matched,
    )
