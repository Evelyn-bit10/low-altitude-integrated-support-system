# -*- coding: utf-8 -*-
"""进离港排序接口。

  POST /api/seq/order  按给定飞行器列表给出确定性排序建议
  GET  /api/seq/order  用当前态势里的进近 / 悬停 / 待命飞行器生成排序
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services.sequencing import sequence

router = APIRouter()


class SeqFlight(BaseModel):
    id: str
    eta_sec: float = 0
    battery_pct: float = 100
    waited_sec: float = 0
    emergency: bool = False
    phase: str = "APPROACH"


class SeqRequest(BaseModel):
    flights: list[SeqFlight] = Field(default_factory=list)
    runway_free_sec: float = 0
    min_separation_sec: float = 45
    slow_flight: bool = True


@router.post("/seq/order")
def seq_order(body: SeqRequest):
    result = sequence(
        [f.model_dump() for f in body.flights],
        body.runway_free_sec,
        body.min_separation_sec,
        body.slow_flight,
    )
    return {"ok": True, "source": "request", **result}


@router.get("/seq/order")
def seq_order_from_traffic(request: Request):
    """从当前交通态势取候选（缺少 ETA 时按 0 处理，仅作演示）。"""
    store = request.app.state.traffic
    items = store.snapshot() if hasattr(store, "snapshot") else []
    flights = []
    for t in items:
        phase = str(t.get("phase", "")).upper()
        if phase not in ("APPROACH", "HOVER", "STANDBY"):
            continue
        flights.append({
            "id": t.get("id"),
            "eta_sec": 0,
            "battery_pct": t.get("battery_pct") or 100,
            "emergency": bool(t.get("emergency")),
            "phase": phase,
        })
    result = sequence(flights)
    return {"ok": True, "source": "traffic", "candidates": len(flights), **result}
