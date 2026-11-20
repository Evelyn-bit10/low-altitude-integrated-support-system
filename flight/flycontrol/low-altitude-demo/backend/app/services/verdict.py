# -*- coding: utf-8 -*-
"""确定性建议结论码（advisory 的权威结论来源）。

模型只能解释这份结论，不能改写它。所有字段都是纯函数计算、无副作用，
这样 /api/ai/advice 和 /api/ai/verdict 能拿到完全一致的结果。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..engines import risk as risk_engine

CONCLUSION_AVAILABLE = "AVAILABLE_CANDIDATES"
CONCLUSION_NO_CANDIDATE = "NO_AVAILABLE_CANDIDATE"
CONCLUSION_INSUFFICIENT = "INSUFFICIENT_DATA"

CONCLUSION_LABELS = {
    CONCLUSION_AVAILABLE: "存在可用候选",
    CONCLUSION_NO_CANDIDATE: "无可用候选",
    CONCLUSION_INSUFFICIENT: "数据不足",
}

# 运行最低能见度与 risk / simulate 引擎的红线保持一致（500 m）。
MIN_VISIBILITY_M = 500.0


def _available(candidates: List[dict]) -> List[dict]:
    return [c for c in (candidates or []) if c.get("available")]


def _meteo_redlines(context: Dict[str, Any], max_crosswind: Optional[float],
                    min_visibility: float) -> List[str]:
    reasons: List[str] = []
    meteo = context.get("meteo") or {}
    ws = meteo.get("wind_speed")
    vis = meteo.get("visibility")
    if ws is not None and max_crosswind is not None and float(ws) > max_crosswind:
        reasons.append("风速 %s m/s 超过机型侧风限制 %s m/s" % (ws, max_crosswind))
    if vis is not None and float(vis) < min_visibility:
        reasons.append("能见度 %s m 低于运行最低标准 %s m" % (vis, min_visibility))
    return reasons


def build_verdict(context: Dict[str, Any], limits: Optional[Dict[str, Any]] = None,
                  rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从已构建的上下文里产出确定性结论码与红线。

    ``limits`` / ``rules`` 仅用于展示约束与红线，缺省时取保守默认值。
    """
    candidates = context.get("candidates") or []
    available = _available(candidates)
    no_current = not context.get("current_program")

    if no_current:
        code = CONCLUSION_INSUFFICIENT
        refusal_reason = "没有当前飞行程序，无法进行确定性风险评估，已拒绝调用大模型。"
    elif not available:
        code = CONCLUSION_NO_CANDIDATE
        refusal_reason = "8 个方向均无可用候选，已拒绝调用大模型。"
    else:
        code = CONCLUSION_AVAILABLE
        refusal_reason = None

    recommended: Optional[Dict[str, Any]] = None
    if available:
        rec = available[0]  # rank_candidates 已按评分排序
        recommended = {
            "direction": rec.get("direction"),
            "score": rec.get("score"),
            "mode": rec.get("mode"),
            "fallback": bool(rec.get("fallback")),
            "reasons": rec.get("reasons") or [],
            "metrics": rec.get("metrics") or {},
        }

    program_type = context.get("program_type") or "arrival"
    moc_key = "MOC_APPROACH" if program_type != "departure" else "MOC_DEPARTURE"
    moc = float((rules or {}).get(moc_key, 75 if program_type != "departure" else 90))
    max_crosswind = float((limits or {}).get("max_crosswind") or 12.0)

    hard_forbid_reasons: List[str] = []
    if not no_current:
        risk = context.get("risk")
        if isinstance(risk, dict) and risk.get("level") == risk_engine.FORBID:
            hard_forbid_reasons.append("环境风险评估为禁飞级（FORBID）")
    hard_forbid_reasons.extend(
        _meteo_redlines(context, max_crosswind, MIN_VISIBILITY_M))

    return {
        "code": code,
        "label": CONCLUSION_LABELS[code],
        "refusal_reason": refusal_reason,
        "recommended": recommended,
        "available_count": len(available),
        "total_count": len(candidates),
        "no_current_program": bool(no_current),
        "hard_forbid": bool(hard_forbid_reasons),
        "hard_forbid_reasons": hard_forbid_reasons,
        "constraints": {
            "max_crosswind_ms": max_crosswind,
            "min_visibility_m": MIN_VISIBILITY_M,
            "moc_%s_m" % ("approach" if program_type != "departure" else "departure"): moc,
        },
    }
