# -*- coding: utf-8 -*-
"""态势历史查询接口。

  GET /api/history/tracks   最近 N 分钟的航迹样本
  GET /api/history/summary  按分钟分桶的聚合（唯一航迹 / 样本数 / 电量 / 速度）
  GET /api/history/stats    历史表规模与保留期
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _history(request: Request):
    store = getattr(request.app.state, "traffic", None)
    return getattr(store, "history", None) if store is not None else None


@router.get("/history/tracks")
def history_tracks(request: Request, minutes: int = 60, limit: int = 500):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    return {"ok": True, **history.recent(minutes, limit)}


@router.get("/history/summary")
def history_summary(request: Request, minutes: int = 60, bucket_sec: int = 60):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    return {"ok": True, **history.summary(minutes, bucket_sec)}


@router.get("/history/stats")
def history_stats(request: Request):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    return {"ok": True, **history.stats()}
