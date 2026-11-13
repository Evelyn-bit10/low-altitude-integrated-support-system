# -*- coding: utf-8 -*-
"""运维与资料管理接口。

  GET    /api/metrics          运行时指标（帧耗时、候选边、计数）
  GET    /api/devices          设备台账
  POST   /api/devices          新增设备
  PUT    /api/devices/{id}     修改设备
  DELETE /api/devices/{id}     删除设备
  GET    /api/routes           路线（航路）管理
  POST   /api/routes
  PUT    /api/routes/{id}
  DELETE /api/routes/{id}

设备/路线都落盘到 `data/*.json`，重启不丢；写操作需要 admin 角色（见 app/services/auth.py）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.metrics import METRICS

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")
_lock = threading.Lock()


def _path(name: str) -> str:
    return os.path.join(_DATA_DIR, name)


def _load(name: str, default: Any) -> Any:
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(name: str, data: Any) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp = _path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path(name))


# ------------------------------------------------------------------ 指标

@router.get("/metrics")
def metrics(request: Request):
    """运行时指标 + 去重/推送/影子的摘要，供监控与排障。"""
    out: Dict[str, Any] = {"metrics": METRICS.snapshot()}
    store = getattr(request.app.state, "store", None)
    if store is not None:
        out["recommend"] = getattr(store, "last_recommend", None)
        out["recommend_history"] = list(getattr(store, "recommend_history", []) or [])[-10:]
        out["program"] = {
            "direction": getattr(store.current_program, "direction", None),
            "std_name": getattr(store.current_program, "std_name", None),
        }
    ts = getattr(request.app.state, "traffic", None)
    if ts is not None:
        out["traffic"] = ts.stats()
        shadow = getattr(ts, "shadow", None)
        if shadow is not None:
            out["shadow"] = shadow.stats()
        eng = getattr(ts, "engine", None)
        if eng is not None:
            sigmas = [t.kf.sigma() for t in eng.tracks.values() if t.kf is not None]
            out["kalman"] = {
                "tracks": len(sigmas),
                "sigma_mean": round(sum(sigmas) / len(sigmas), 2) if sigmas else 0.0,
                "sigma_max": round(max(sigmas), 2) if sigmas else 0.0,
                "sigma_scale": round(getattr(eng, "sigma_scale", 1.0), 3),
            }
    return out


# ------------------------------------------------------------------ 设备台账

class Device(BaseModel):
    name: str = Field(..., description="设备名称")
    source_key: str = Field(..., description="报文里的 source_node，如 A-RID")
    kind: str = Field("rid", description="rid / adsb / radar / camera")
    sigma_m: float = Field(20.0, ge=1.0, le=500.0, description="位置误差 σ（米）")
    quality: float = Field(0.6, ge=0.0, le=1.0)
    status: str = Field("online", description="online / offline / maintenance")
    note: str = ""


@router.get("/devices")
def list_devices():
    return {"devices": _load("devices.json", [])}


@router.post("/devices")
def create_device(body: Device):
    with _lock:
        items = _load("devices.json", [])
        if any(d["source_key"] == body.source_key for d in items):
            raise HTTPException(400, "source_key 已存在：%s" % body.source_key)
        row = body.model_dump()
        row.update(id="DEV-" + uuid.uuid4().hex[:8], created_at=time.time())
        items.append(row)
        _save("devices.json", items)
    return {"ok": True, "device": row}


@router.put("/devices/{dev_id}")
def update_device(dev_id: str, body: Device):
    with _lock:
        items = _load("devices.json", [])
        for d in items:
            if d.get("id") == dev_id:
                d.update(body.model_dump())
                d["updated_at"] = time.time()
                _save("devices.json", items)
                return {"ok": True, "device": d}
    raise HTTPException(404, "设备不存在：%s" % dev_id)


@router.delete("/devices/{dev_id}")
def delete_device(dev_id: str):
    with _lock:
        items = _load("devices.json", [])
        keep = [d for d in items if d.get("id") != dev_id]
        if len(keep) == len(items):
            raise HTTPException(404, "设备不存在：%s" % dev_id)
        _save("devices.json", keep)
    return {"ok": True, "deleted": dev_id}


# ------------------------------------------------------------------ 路线

class RoutePoint(BaseModel):
    x: float
    y: float
    z: float = 100.0


class Route(BaseModel):
    name: str
    kind: str = Field("corridor", description="corridor / no_fly / route")
    points: List[RoutePoint] = Field(default_factory=list)
    floor_agl: float = 0.0
    ceiling_agl: float = 300.0
    note: str = ""


@router.get("/routes")
def list_routes():
    return {"routes": _load("routes.json", [])}


@router.post("/routes")
def create_route(body: Route):
    with _lock:
        items = _load("routes.json", [])
        row = body.model_dump()
        row["points"] = [p.model_dump() if hasattr(p, "model_dump") else p for p in body.points]
        row.update(id="RTE-" + uuid.uuid4().hex[:8], created_at=time.time())
        items.append(row)
        _save("routes.json", items)
    return {"ok": True, "route": row}


@router.put("/routes/{rid}")
def update_route(rid: str, body: Route):
    with _lock:
        items = _load("routes.json", [])
        for r in items:
            if r.get("id") == rid:
                r.update(body.model_dump())
                r["points"] = [p.model_dump() if hasattr(p, "model_dump") else p for p in body.points]
                r["updated_at"] = time.time()
                _save("routes.json", items)
                return {"ok": True, "route": r}
    raise HTTPException(404, "路线不存在：%s" % rid)


@router.delete("/routes/{rid}")
def delete_route(rid: str):
    with _lock:
        items = _load("routes.json", [])
        keep = [r for r in items if r.get("id") != rid]
        if len(keep) == len(items):
            raise HTTPException(404, "路线不存在：%s" % rid)
        _save("routes.json", keep)
    return {"ok": True, "deleted": rid}
