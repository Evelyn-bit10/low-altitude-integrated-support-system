# -*- coding: utf-8 -*-
"""进离港排序（确定性、可复现）。

产品分析文档 2.2 第一条：系统能逐架判出能不能起降，但多架挤在同一时间窗时
没有整体安排。这里补一个**确定性**排序器，给出「谁先落、等多久、剩余电量」：

  * N <= 7：枚举所有放行顺序，按「安全落地数 > 加权等待 > 最低电量」取最优；
  * N > 7：贪心（紧急 > 电量低 > ETA 早）+ 2-opt 局部改进；
  * 等待期间默认按「慢飞」耗电（0.0014/s），可关闭（盘旋 0.004/s）。

边界：本模块只排序，不改变任何单机阈值判定；每架仍要过飞手端 / 通讯端的
检查。算法是精确枚举与贪心，不是需求里的 MILP——接口保持稳定，后续可替换。
"""
from __future__ import annotations

from itertools import permutations
from typing import Any, Dict, List, Optional

MIN_SEP_S = 45.0          # 最小时间间隔（秒），与 experiments/rl_seq 一致
SPIRAL_DRAIN = 0.0040     # 盘旋等待：每秒耗电（占满电比例）
SLOW_DRAIN = 0.0014       # 慢飞等待：每秒耗电（比盘旋省约 65%）
EMERGENCY_WEIGHT = 3.0    # 紧急状态的等待代价加权
EXACT_LIMIT = 7           # 不超过这个数量时枚举全排列


def _norm(flight: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(flight.get("id") or "?"),
        "eta_sec": max(0.0, float(flight.get("eta_sec") or 0.0)),
        "battery_pct": max(0.0, min(100.0, float(flight.get("battery_pct", 100.0)))),
        "waited_sec": max(0.0, float(flight.get("waited_sec") or 0.0)),
        "emergency": bool(flight.get("emergency")),
        "phase": str(flight.get("phase") or "APPROACH"),
    }


def simulate(order: List[Dict[str, Any]], runway_free_sec: float,
             min_separation_sec: float, slow_flight: bool) -> Dict[str, Any]:
    """按给定顺序模拟落地，返回顺序表与汇总指标。"""
    t_free = max(0.0, float(runway_free_sec))
    rows = []
    landed = 0
    total_wait = 0.0
    weighted_wait = 0.0
    min_battery = 1.0

    for flight in order:
        eta = flight["eta_sec"]
        land_at = max(t_free, eta)
        wait = land_at - eta
        drain = (SLOW_DRAIN if slow_flight else SPIRAL_DRAIN) * wait
        battery_after = flight["battery_pct"] / 100.0 - drain
        ok = battery_after > 0
        if ok:
            landed += 1
            t_free = land_at + min_separation_sec
        else:
            battery_after = 0.0
        total_wait += wait
        weighted_wait += wait * (EMERGENCY_WEIGHT if flight["emergency"] else 1.0)
        min_battery = min(min_battery, battery_after)
        rows.append({
            "id": flight["id"],
            "eta_sec": round(eta, 1),
            "land_at_sec": round(land_at, 1),
            "wait_sec": round(wait, 1),
            "battery_after_pct": round(battery_after * 100.0, 1),
            "emergency": flight["emergency"],
            "landed": ok,
        })

    return {
        "order": rows,
        "landed_count": landed,
        "total_wait_sec": round(total_wait, 1),
        "weighted_wait_sec": round(weighted_wait, 1),
        "min_battery_after_pct": round(min_battery * 100.0, 1),
        "all_landed": landed == len(order),
    }


def _score(result: Dict[str, Any]) -> tuple:
    return (result["landed_count"], -result["weighted_wait_sec"], result["min_battery_after_pct"])


def _greedy(flights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(flights, key=lambda f: (
        0 if f["emergency"] else 1,
        f["battery_pct"],
        f["eta_sec"],
    ))


def _two_opt(order: List[Dict[str, Any]], flights: List[Dict[str, Any]],
             runway_free_sec: float, min_separation_sec: float,
             slow_flight: bool) -> tuple:
    best = list(order)
    best_result = simulate(best, runway_free_sec, min_separation_sec, slow_flight)
    improved = True
    rounds = 0
    while improved and rounds < 3:
        improved = False
        rounds += 1
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + [best[j]] + best[i + 1:j] + [best[i]] + best[j + 1:]
                result = simulate(candidate, runway_free_sec, min_separation_sec, slow_flight)
                if _score(result) > _score(best_result):
                    best, best_result, improved = candidate, result, True
    return best, best_result


def sequence(flights: Optional[List[Dict[str, Any]]] = None,
             runway_free_sec: float = 0.0,
             min_separation_sec: float = MIN_SEP_S,
             slow_flight: bool = True) -> Dict[str, Any]:
    items = [_norm(f) for f in (flights or [])]
    if not items:
        return {
            "method": "empty",
            "order": [],
            "landed_count": 0,
            "total_wait_sec": 0.0,
            "weighted_wait_sec": 0.0,
            "min_battery_after_pct": 100.0,
            "all_landed": True,
            "rationale": ["没有待排序的飞行器。"],
            "params": {"runway_free_sec": 0.0,
                       "min_separation_sec": float(min_separation_sec),
                       "slow_flight": bool(slow_flight)},
        }

    sep = max(0.0, float(min_separation_sec))
    if len(items) <= EXACT_LIMIT:
        method = "exact"
        best_order: Optional[List[Dict[str, Any]]] = None
        best_result: Optional[Dict[str, Any]] = None
        for perm in permutations(items):
            result = simulate(perm, runway_free_sec, sep, slow_flight)
            if best_result is None or _score(result) > _score(best_result):
                best_order, best_result = list(perm), result
    else:
        method = "greedy+2opt"
        best_order, best_result = _two_opt(_greedy(items), items, runway_free_sec, sep, slow_flight)

    return {
        "method": method,
        **best_result,
        "rationale": _rationale(best_order, best_result, slow_flight),
        "params": {
            "runway_free_sec": round(float(runway_free_sec), 1),
            "min_separation_sec": sep,
            "slow_flight": bool(slow_flight),
        },
    }


def _rationale(order: List[Dict[str, Any]], result: Dict[str, Any],
               slow_flight: bool) -> List[str]:
    lines: List[str] = []
    rows = result["order"]
    if rows:
        first = rows[0]
        if first["emergency"]:
            lines.append("%s 处于紧急状态，优先放行。" % first["id"])
        elif first["battery_after_pct"] < 25:
            lines.append("%s 电量较低，先落地避免耗尽。" % first["id"])
        else:
            lines.append("%s 首个放行（等待代价最小）。" % first["id"])

    if not result["all_landed"]:
        failed = [r["id"] for r in rows if not r["landed"]]
        lines.append("%s 在等待中电量耗尽，建议改派或优先保障。" % "、".join(failed))

    waits = [r for r in rows if r["wait_sec"] > 0]
    if waits:
        lines.append("其余 %d 架需要等待，最长约 %.0f 秒。"
                     % (len(waits), max(r["wait_sec"] for r in waits)))
    if slow_flight:
        lines.append("等待期间按慢飞耗电估算（0.0014/s），比盘旋省约 65%。")
    return lines
