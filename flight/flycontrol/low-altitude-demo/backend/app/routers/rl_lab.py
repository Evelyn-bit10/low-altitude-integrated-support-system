# -*- coding: utf-8 -*-
"""RL 实验室接口: 把训练好的策略权重暴露给可视化页面。

提供:
  GET /api/rl/model  -> 网络权重 + 归一化参数 + 决策阈值 + 训练曲线 + 指标

页面 platform/portal/rl_lab.html 直接用这些数据在浏览器里跑前向推理，
所以拖动滑杆看概率变化是**零延迟**的（不发请求）。

只读接口, 不参与业务。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from app.services import replay

log = logging.getLogger(__name__)

router = APIRouter()

_RL_DIR = Path(__file__).resolve().parents[2] / "experiments" / "rl_dedup"

_cache: Dict[str, Any] = {"mtime": 0.0, "data": None}


def _load() -> Dict[str, Any]:
    """读权重/参数/曲线，带 mtime 缓存（重训后自动刷新）。"""
    files = {
        "weights": _RL_DIR / "policy_weights.json",
        "params": _RL_DIR / "rl_params.json",
        "history": _RL_DIR / "ppo_history.json",
        "meta": _RL_DIR / "ppo_meta.json",
    }
    if not files["weights"].exists():
        raise HTTPException(status_code=404, detail="策略权重不存在: %s" % files["weights"])
    mtime = max(p.stat().st_mtime for p in files.values() if p.exists())
    if _cache["data"] is not None and _cache["mtime"] == mtime:
        return _cache["data"]

    def read(key: str) -> dict:
        p = files[key]
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    w = read("weights")
    params = read("params")
    history = read("history")
    meta = read("meta")

    data = {
        "features": w.get("features") or meta.get("features") or [],
        "mean": w.get("mean") or meta.get("mean") or [],
        "std": w.get("std") or meta.get("std") or [],
        "weights": w.get("weights") or {},
        "threshold": float(params.get("threshold", 0.5)),
        "decision_rule": params.get("decision_rule", ""),
        "safety_rules": params.get("safety_rules", []),
        "expected": params.get("expected") or w.get("test") or {},
        "rule_baseline": params.get("rule_baseline") or w.get("rule") or {},
        "history": history if isinstance(history, list) else [],
        "model_info": {
            "layers": [len(w.get("features") or []), 64, 64, 1],
            "params": _count_params(w.get("weights") or {}),
            "trained_on": "规则热启动 8 轮(BCE) + 逐边 PPO 30 轮",
        },
    }
    _cache.update(mtime=mtime, data=data)
    return data


def _count_params(weights: Dict[str, Any]) -> int:
    total = 0
    for v in weights.values():
        n = 1
        for dim in _shape(v):
            n *= dim
        total += n
    return total


def _shape(v):
    if isinstance(v, list):
        if v and isinstance(v[0], list):
            return (len(v), len(v[0]))
        return (len(v),)
    return ()


@router.get("/rl/model")
def rl_model():
    """策略权重与训练元数据（供 rl_lab.html 在浏览器里做推理）。"""
    return _load()


@router.get("/rl/health")
def rl_health():
    try:
        d = _load()
        return {"ok": True, "features": len(d["features"]), "threshold": d["threshold"],
                "params": d["model_info"]["params"]}
    except HTTPException as exc:
        return {"ok": False, "detail": exc.detail}


@router.get("/rl/live")
def rl_live(request: Request, n: int = 60):
    """影子模式的实时判定（最近 n 条），供页面"边飞边看"。

    未开启影子模式时 enabled=false，rows 为空。
    """
    ts = getattr(request.app.state, "traffic", None)
    shadow = getattr(ts, "shadow", None) if ts is not None else None
    if shadow is None:
        return {"enabled": False, "reason": "影子模式未加载", "stats": {}, "rows": []}
    return {
        "enabled": bool(shadow.enabled),
        "reason": shadow.reason,
        "stats": shadow.stats(),
        "rows": shadow.recent_rows(n) if shadow.enabled else [],
        "features": (shadow.policy.features if getattr(shadow, "policy", None) else []),
    }


@router.get("/rl/compare")
def rl_compare(scenario: str = "swarm", frames: int | None = None):
    """单个场景：规则 vs PPO，用**真值**打分（错配/漏配/碎片数）。"""
    try:
        return replay.compare(scenario, frames)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rl/compare/all")
def rl_compare_all(frames: int | None = None):
    """四个场景一次跑完（首次约 15 秒，之后走缓存）。"""
    return {"scenarios": replay.compare_all(frames)}
