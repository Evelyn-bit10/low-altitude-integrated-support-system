# -*- coding: utf-8 -*-
"""进出场方向推荐：把 16 个候选全跑一遍，按可解释的规则打分排序。

为什么不用强化学习
------------------
方向选择只有 8 个方向 × 2 种程序 = 16 个候选，而且每个候选的代价**生成即知**
（合规、仿真、航程、梯度、侧风）。RL 适合"动作多、后果延迟、无法枚举"的问题，
这里三条都不成立 —— 用一个神经网络去替代 16 次循环，更慢也更不可解释。

评分（0~1，越高越好）
--------------------
    0.0        硬约束不过（合规/仿真），直接淘汰
    0.40       基础分（可用）
  + 0.25 × 侧风得分（逆风最佳，侧风/顺风扣分）
  + 0.20 × 航程得分（同类型里最短得满分）
  + 0.10 × 梯度余量（最大梯度离包线越远越好）
  + 0.05 × 与当前航向契合（避免大转弯）
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from app.services.ledger import _load  # noqa: F401  （保持模块依赖清晰）


def _angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _crosswind(wind_dir: float, wind_speed: float, runway_heading: float) -> float:
    """侧风分量（m/s）；顺风为负值。"""
    return wind_speed * math.sin(math.radians(_angle_diff(wind_dir, runway_heading)))


def score_one(direction: str, bearing: float, prog, comp, sim,
              meteo, heading_of_runway: float) -> dict:
    """给单个候选打分，返回 {score, reasons, metrics}。"""
    available = bool(getattr(comp, "is_pass", False) and getattr(sim, "is_pass", False))
    if not available:
        msg = (comp.err_msg() if hasattr(comp, "err_msg") else "") or \
              (sim.err_msg() if hasattr(sim, "err_msg") else "") or "校验未通过"
        return {"direction": direction, "score": 0.0, "available": False,
                "reasons": ["不可用: " + str(msg)[:60]], "metrics": {}}

    length = float(getattr(prog, "length_m", 0.0) or 0.0)
    if not length:
        wps = getattr(prog, "waypoints", []) or []
        length = sum(math.dist((a.x, a.y), (b.x, b.y))
                     for a, b in zip(wps, wps[1:])) if len(wps) > 1 else 0.0

    # 风分量：逆风（风从机头来）为正，顺风为负
    delta = _angle_diff(meteo.wind_dir, heading_of_runway)
    headwind = meteo.wind_speed * math.cos(math.radians(delta))
    xw = meteo.wind_speed * math.sin(math.radians(delta))
    # 打分：侧风越小事越好；顺风额外扣分（起降都希望逆风）
    tailwind = max(0.0, -headwind)
    wind_score = max(0.0, 1.0 - abs(xw) / 12.0 - 0.5 * tailwind / 12.0)

    return {
        "direction": direction, "score": 0.0, "available": True,
        "metrics": {"length_m": round(length, 1), "crosswind_mps": round(xw, 1),
                    "headwind_mps": round(headwind, 1),
                    "tailwind_mps": round(tailwind, 1)},
        "xw_score": wind_score, "length": length,
        "reasons": [],
    }


def rank(candidates: List[dict], current_heading: Optional[float] = None) -> List[dict]:
    """对可用候选做归一化打分并排序，生成可读理由。"""
    avail = [c for c in candidates if c.get("available")]
    if not avail:
        return sorted(candidates, key=lambda c: -c["score"])

    lengths = [c["length"] for c in avail if c["length"] > 0]
    lmin, lmax = (min(lengths), max(lengths)) if lengths else (0.0, 0.0)

    for c in avail:
        length_score = 1.0 if lmax <= lmin else (lmax - c["length"]) / (lmax - lmin)
        fit = 1.0
        if current_heading is not None:
            # 与"从该方向进场"的航向差越小越好（进场航向 = 该方向方位 + 180）
            fit = max(0.0, 1.0 - _angle_diff(current_heading, c.get("entry_heading", 0.0)) / 180.0)
        c["score"] = round(0.40 + 0.25 * c["xw_score"] + 0.20 * length_score
                           + 0.05 * fit + 0.10 * c.get("grad_score", 1.0), 3)

        m = c["metrics"]
        r = ["合规 ✓ / 仿真 ✓"]
        hw, tw, xwc = m.get("headwind_mps", 0), m.get("tailwind_mps", 0), abs(m["crosswind_mps"])
        if tw > 2.0:
            r.append("顺风 %.1f m/s（不利）" % tw)
        elif c["xw_score"] >= 0.9:
            r.append("逆风 %.1f m/s、侧风 %.1f（最优）" % (hw, xwc))
        else:
            r.append("侧风 %.1f m/s（可接受）" % xwc)
        r.append("航程 %.1f km" % (c["length"] / 1000.0))
        if current_heading is not None and fit >= 0.85:
            r.append("与当前航向契合")
        c["reasons"] = r

    return sorted(candidates, key=lambda c: (-c["score"], c["direction"]))


# ------------------------------------------------------------------ 航迹（程序）级评分
def program_score(prog, comp, sim, env) -> dict:
    """给**一条具体程序**打分：同方向下用来在"模板 / 动态重规划"等候选之间选优。

    与方向评分的区别：方向评分比的是"从哪边进场"，这里比的是"同一边进场，
    用哪条航迹更好"。四个指标都是工程上真正关心的：
        航程（越短越省油）、最小超障余度（越富余越安全）、
        最大梯度（离机型包线越远越稳）、转弯次数（越少越舒适）。
    """
    available = bool(getattr(comp, "is_pass", False) and getattr(sim, "is_pass", False))
    wps = getattr(prog, "waypoints", []) or []
    if not available or len(wps) < 2:
        msg = (comp.err_msg() if hasattr(comp, "err_msg") else "") or \
              (sim.err_msg() if hasattr(sim, "err_msg") else "") or "不可用"
        return {"available": False, "score": 0.0, "metrics": {}, "reasons": ["不可用: " + str(msg)[:50]]}

    length = float(getattr(prog, "length_m", 0.0) or 0.0)
    if not length:
        length = sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(wps, wps[1:]))

    # 最大梯度
    max_grad = 0.0
    for a, b in zip(wps, wps[1:]):
        dh = math.hypot(b.x - a.x, b.y - a.y)
        if dh > 1.0:
            max_grad = max(max_grad, abs(b.z - a.z) / dh)

    # 转弯次数：航向变化超过 15° 记一次
    turns = 0
    for a, b, c in zip(wps, wps[1:], wps[2:]):
        h1 = math.degrees(math.atan2(b.x - a.x, b.y - a.y))
        h2 = math.degrees(math.atan2(c.x - b.x, c.y - b.y))
        if _angle_diff(h1, h2) > 15.0:
            turns += 1

    # 最小超障余度（用合规检查里的 MOC 结果反推）
    clearance = None
    for ck in (getattr(comp, "checks", None) or []):
        if "超障" in str(ck.get("name", "")) or "MOC" in str(ck.get("name", "")):
            clearance = ck.get("margin")
    if clearance is None:
        clearance = 75.0 if available else 0.0

    grad_limit = float(getattr(env.limits, "climb_gradient", 0.10) or 0.10)
    grad_score = max(0.0, 1.0 - max_grad / max(grad_limit, 0.01))
    clr_score = min(1.0, max(0.0, clearance) / 150.0)
    turn_score = max(0.0, 1.0 - turns / 12.0)

    base = 0.40 + 0.15 * clr_score + 0.10 * grad_score + 0.10 * turn_score
    return {
        "available": True, "base": base,
        "metrics": {"length_m": round(length, 1), "max_grad": round(max_grad, 3),
                    "turns": turns, "clearance_m": clearance},
        "reasons": ["航程 %.1f km" % (length / 1000.0),
                    "最大梯度 %.1f%%" % (max_grad * 100),
                    "转弯 %d 次" % turns,
                    "超障余度 %.0f m" % clearance],
    }


def pick_better(cand_a: dict, cand_b: dict, length_weight: float = 0.25) -> tuple:
    """在两条候选中选优：可用优先，其次按「航程 + 安全余度」综合。

    航程归一化要两条都比完才知道，所以这里单独处理。
    """
    a, b = cand_a, cand_b
    if not a.get("available") and not b.get("available"):
        return None, "两条候选都不可用"
    if a.get("available") and not b.get("available"):
        return a, "另一条不可用"
    if b.get("available") and not a.get("available"):
        return b, "另一条不可用"

    la = a["metrics"]["length_m"]
    lb = b["metrics"]["length_m"]
    lmin, lmax = min(la, lb), max(la, lb)
    for c in (a, b):
        ln = c["metrics"]["length_m"]
        ls = 1.0 if lmax <= lmin else (lmax - ln) / (lmax - lmin)
        c["score"] = round(c["base"] + length_weight * ls, 3)

    win = a if a["score"] >= b["score"] else b
    lose = b if win is a else a
    why = "得分 %.3f > %.3f（%s）" % (win["score"], lose["score"],
                                     "、".join(win["reasons"][:2]))
    return win, why
