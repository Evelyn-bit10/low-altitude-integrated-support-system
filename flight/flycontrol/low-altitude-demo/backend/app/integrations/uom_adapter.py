# -*- coding: utf-8 -*-
"""统一的「对外推送」报文适配层。

把本系统的 canonical 数据（`shared/contract.md`）翻译成外部平台（民航局 UOM /
地方低空平台）的消息格式。**所有字段映射集中在本文件**，接入真实规范时只改这里。

消息信封（各平台通用，字段名可按需替换）::

    {
      "msgId":    "唯一消息 ID（幂等键）",
      "msgType":  "SURVEILLANCE" | "FLIGHT_PROGRAM" | "METEO" | "ALERT" | "HEARTBEAT",
      "sendTime": "2026-10-22T10:00:00+00:00",
      "source":   {"system": "LOWA-SKY", "nodeId": "NODE-A"},
      "version":  "1.1",
      "payload":  { ... }
    }

> 说明：真实 UOM 接口规范各版本字段名不同（如 `uasId`/`uavId`、`altMsl`/`altitude`），
> 这里采用一套「中性字段名 + 集中映射表」的做法，落地时改 `FIELD_MAP` 即可。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

SPEC_VERSION = "1.1"
SYSTEM_CODE = "LOWA-SKY"

# 外部平台字段名映射（改这里即可适配具体规范）
FIELD_MAP = {
    "uas_id": "uasId",
    "reg_no": "regNo",
    "lat": "lat",
    "lon": "lon",
    "alt_msl": "altMsl",
    "speed": "groundSpeed",
    "heading": "trackAngle",
    "phase": "flightPhase",
    "ts": "occurTime",
}


def _iso(ts: Optional[float] = None) -> str:
    if ts is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def make_msg_id(topic: str, node_id: str, ts: str, body) -> str:
    """按「主题+节点+时间+内容」生成幂等 ID：同一条内容重复采集不会重复推送。"""
    raw = "%s|%s|%s|%s" % (topic, node_id, ts,
                           json.dumps(body, ensure_ascii=False, sort_keys=True))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def envelope(msg_type: str, node_id: str, payload: dict,
             ts: Optional[float] = None) -> dict:
    send_time = _iso(ts)
    msg_id = make_msg_id(msg_type, node_id, send_time, payload)
    return {
        "msgId": msg_id,
        "msgType": msg_type,
        "sendTime": send_time,
        "source": {"system": SYSTEM_CODE, "nodeId": node_id},
        "version": SPEC_VERSION,
        "payload": payload,
    }


# ------------------------------------------------------------------ 各类报文

def track_payload(tracks: List[dict]) -> dict:
    """实时态势（已去重）：一次推一批。"""
    items = []
    for t in tracks:
        items.append({
            FIELD_MAP["uas_id"]: t.get("ua_id") or t.get("id"),
            FIELD_MAP["reg_no"]: t.get("reg_no"),
            FIELD_MAP["lat"]: round(float(t.get("lat", 0.0)), 7),
            FIELD_MAP["lon"]: round(float(t.get("lon", 0.0)), 7),
            FIELD_MAP["alt_msl"]: round(float(t.get("alt_msl", 0.0)), 1),
            FIELD_MAP["speed"]: round(float(t.get("speed", 0.0)), 1),
            FIELD_MAP["heading"]: round(float(t.get("heading", 0.0)), 1),
            FIELD_MAP["phase"]: t.get("phase"),
            FIELD_MAP["ts"]: t.get("ts"),
            # 溯源信息：便于对方核对"这条是哪几路融合出来的"
            "sources": t.get("sources") or [],
            "confidence": t.get("confidence"),
        })
    return {"count": len(items), "tracks": items}


def program_payload(program: dict, airport_code: str) -> dict:
    """飞行程序（进近 / 离场）。"""
    return {
        "airportCode": airport_code,
        "programType": program.get("type"),
        "direction": program.get("direction"),
        "stdName": program.get("std_name"),
        "version": program.get("version"),
        "source": program.get("source"),
        "waypoints": [{"lat": w.get("lat"), "lon": w.get("lon"),
                       "altMsl": w.get("alt_msl"), "speed": w.get("speed")}
                      for w in (program.get("waypoints") or [])],
        "missedApproach": [{"lat": w.get("lat"), "lon": w.get("lon"),
                            "altMsl": w.get("alt_msl")}
                           for w in (program.get("miss_approach") or [])],
    }


def meteo_payload(meteo: dict, airport_code: str) -> dict:
    return {
        "airportCode": airport_code,
        "windSpeed": meteo.get("wind_speed"),
        "windDir": meteo.get("wind_dir"),
        "gust": meteo.get("gust"),
        "visibility": meteo.get("visibility"),
        "cloudBaseAgl": meteo.get("cloud_base_agl", meteo.get("cloud_base")),
        "temperature": meteo.get("temperature"),
        "pressure": meteo.get("pressure"),
        "turbulence": meteo.get("turbulence"),
        "windShear": meteo.get("wind_shear"),
    }


def alert_payload(text: str, level: str = "WARNING", airport_code: str = "") -> dict:
    return {"airportCode": airport_code, "level": level, "text": text}


def message_for(msg_type: str, node_id: str, payload: dict,
                ts: Optional[float] = None) -> dict:
    return envelope(msg_type, node_id, payload, ts)
