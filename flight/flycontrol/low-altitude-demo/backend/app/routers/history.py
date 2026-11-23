# -*- coding: utf-8 -*-
"""态势与事件历史查询接口。

  GET  /api/history/tracks          最近 N 分钟的航迹样本
  GET  /api/history/summary         按分钟分桶的航迹聚合
  GET  /api/history/stats           历史表规模与保留期
  GET  /api/history/events          最近事件（程序 / 环境 / 推送 / 许可）
  GET  /api/history/events/summary  事件按类型计数
  POST /api/permit/record           记录一次许可签发 / 拒绝（飞手端调用，失败静默）
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class PermitRecord(BaseModel):
    id: str
    uav_id: str = ""
    action: str = ""
    level: str = "APPROVE"
    status: str = "approved"
    reasons: List[str] = Field(default_factory=list)


class EventRecord(BaseModel):
    kind: str = "alert"
    subject: str = ""
    level: str = "warn"
    message: str = ""
    source: str = ""


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


@router.get("/history/events")
def history_events(request: Request, minutes: int = 1440, limit: int = 200,
                   kind: Optional[str] = None):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    return {"ok": True, **history.recent_events(minutes, limit, kind)}


@router.get("/history/events/summary")
def history_event_summary(request: Request, minutes: int = 1440):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    return {"ok": True, **history.event_summary(minutes)}


@router.post("/permit/record")
def permit_record(request: Request, body: PermitRecord):
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    level = body.level.upper()
    tone = "info" if level == "APPROVE" else ("warn" if level == "HOLD" else "error")
    message = "%s %s -> %s (%s)" % (body.action or "申请", body.uav_id or "-",
                                     body.level, body.status)
    if body.reasons:
        message += "；" + "；".join(body.reasons[:3])
    history.record_event("permit", body.id, tone, message, "pilot-app")
    return {"ok": True}


@router.post("/events/record")
def event_record(request: Request, body: EventRecord):
    """通用事件上报（通讯态势前端写告警等）。"""
    history = _history(request)
    if history is None:
        return {"ok": False, "detail": "历史存储未启用（HISTORY_ENABLED=0）"}
    level = body.level if body.level in ("info", "warn", "error") else "warn"
    history.record_event(
        (body.kind or "alert")[:32],
        (body.subject or "")[:128],
        level,
        (body.message or "")[:1000],
        (body.source or "")[:64],
    )
    return {"ok": True}
