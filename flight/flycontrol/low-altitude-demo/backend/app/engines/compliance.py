"""引擎 1: 民航合规校验引擎(最小可运行实现)。

对照原伪代码实现 4 项可计算的校验:
  1. MSA 最低安全高度
  2. MOC 超障余度
  3. OAS 障碍物评价面(简化: 进近漏斗 + 下滑道斜面)
  4. 航段爬升/下降梯度

说明: 真实 PANS-OPS OAS 是三维曲面簇(参见 ICAO Doc 8168 Vol.II)。本 Demo 采用
      平面近似(横向线性扩展漏斗 + 下滑道斜面), 结构与规范一致、可计算、可验证,
      生产系统需替换为完整的 OAS 曲面方程组。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from ..domain import AircraftLimits, EnvSnapshot, FlightProgram, Obstacle
from . import geometry as geo


@dataclass
class CheckItem:
    name: str
    passed: bool
    detail: str
    margin: Optional[float] = None


@dataclass
class ComplianceResult:
    passed: bool
    checks: List[CheckItem] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return self.passed

    def err_msg(self) -> str:
        return "; ".join(c.detail for c in self.checks if not c.passed)


def calc_msa(obstacles: List[Obstacle], margin: float) -> float:
    """最低安全高度: 最高障碍物顶部 + 附加余度(AGL 米)。"""
    if not obstacles:
        return margin
    return max(o.top_agl for o in obstacles) + margin


def check_moc(program: FlightProgram, obstacles: List[Obstacle], moc: float) -> CheckItem:
    """超障余度: 航迹各点相对障碍物圆柱的垂直净空须 >= MOC。"""
    min_clear = float("inf")
    worst: Optional[Obstacle] = None
    for w in program.waypoints:
        for o in obstacles:
            if geo.dist2d((w.x, w.y), (o.x, o.y)) <= o.inflated_radius:
                clearance = w.z - o.top_agl
                if clearance < min_clear:
                    min_clear = clearance
                    worst = o
    if worst is None or min_clear >= moc:
        margin = None if worst is None else round(min_clear, 1)
        return CheckItem("MOC超障余度", True,
                         f"各障碍物超障余度均满足(>= {moc}m)", margin)
    return CheckItem("MOC超障余度", False,
                     f"障碍物[{worst.name}]超障余度不足: 需>= {moc}m, 实际 {min_clear:.1f}m",
                     round(min_clear, 1))


def check_oas(env: EnvSnapshot, half_width0: float, spread: float,
              glideslope_deg: float, moc: float, final_dist: float) -> CheckItem:
    """简化 OAS(最终进近评价面, 与跑道固连, 独立于具体规划航迹)。

    以跑道入口为原点, 沿进近来向(跑道航向的反方向)向后延伸 final_dist 米:
        半宽  W(s) = half_width0 + spread * s
        高度  H(s) = max(0, tan(glideslope) * s - moc)
    障碍物顶高高于 H(s) 且水平投影落在 W(s) 内即判定侵入。

    该评价面保护的是"最终进近/着陆区", 因此动态障碍若位于进场航路的
    中间段, 可由航迹规划横向绕飞规避; 若侵入最终进近面则不可绕飞, 需封场。
    """
    heading = env.airport.runway_heading
    ux, uy = math.sin(math.radians(heading)), math.cos(math.radians(heading))
    tan_gs = math.tan(math.radians(glideslope_deg))
    for o in env.obstacles:
        s = -(o.x * ux + o.y * uy)              # 距入口沿进近方向的投影距离
        if s < 0 or s > final_dist:
            continue
        lateral = math.hypot(o.x + s * ux, o.y + s * uy)
        if lateral <= half_width0 + spread * s:
            required = max(0.0, tan_gs * s - moc)
            if o.top_agl > required:
                return CheckItem("OAS评价面", False,
                                 f"障碍物[{o.name}]侵入最终进近评价面: "
                                 f"顶高 {o.top_agl:.0f}m > 允许 {required:.0f}m "
                                 f"(距入口 {s:.0f}m, 侧向 {lateral:.0f}m)",
                                 round(required - o.top_agl, 1))
    return CheckItem("OAS评价面", True, "最终进近评价面(OAS)无障碍物侵入")


def check_gradients(program: FlightProgram, limits: AircraftLimits) -> CheckItem:
    """航段梯度: 相邻航路点间实际爬升/下降梯度须在机型包线内。"""
    max_used = 0.0
    max_allowed = max(limits.climb_gradient, limits.descent_gradient)
    for i in range(len(program.waypoints) - 1):
        p = program.waypoints[i]
        q = program.waypoints[i + 1]
        h = math.hypot(q.x - p.x, q.y - p.y)
        if h < 1e-6:
            continue
        g = abs(q.z - p.z) / h
        max_used = max(max_used, g)
    if max_used <= max_allowed + 1e-6:
        return CheckItem("航段梯度", True,
                         f"最大航段梯度 {max_used*100:.1f}% 在机型包线内(<= {max_allowed*100:.1f}%)",
                         round(max_allowed - max_used, 4))
    return CheckItem("航段梯度", False,
                     f"最大航段梯度 {max_used*100:.1f}% 超出机型包线 {max_allowed*100:.1f}%",
                     round(max_allowed - max_used, 4))


def check_full(program: FlightProgram, env: EnvSnapshot,
               rules: dict, limits: AircraftLimits) -> ComplianceResult:
    """全量合规校验, 对应原伪代码 AviFullCheck。"""
    moc = float(rules.get("MOC_APPROACH", 75)) if program.program_type != "departure" \
        else float(rules.get("MOC_DEPARTURE", 90))
    msa_margin = float(rules.get("MSA_MARGIN", 300))
    hw0 = float(rules.get("OAS_HALF_WIDTH0", 100))
    spread = float(rules.get("OAS_SPREAD", 0.15))
    gs = float(rules.get("OAS_GLIDESLOPE_DEG", 5.7))
    final_dist = float(rules.get("OAS_FINAL_DIST", 1500))

    msa = calc_msa(env.obstacles, msa_margin)
    checks = [
        CheckItem("MSA最低安全高度", True,
                  f"MSA = {msa:.0f}m (最高障碍物 + {msa_margin}m)"),
        check_moc(program, env.obstacles, moc),
        check_gradients(program, limits),
    ]
    # 进近才做 OAS 最终进近面校验; 离场由 MOC 梯度面覆盖
    if program.program_type != "departure":
        checks.append(check_oas(env, hw0, spread, gs, moc, final_dist))

    passed = all(c.passed for c in checks)
    return ComplianceResult(passed, checks)
