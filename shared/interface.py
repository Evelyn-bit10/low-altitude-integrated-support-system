# -*- coding: utf-8 -*-
"""
低空起降点系统 · 统一数据接口 Python 适配层 (canonical v1.1)
==============================================================
与 shared/interface.js 镜像, 作为 flycontrol 后端及其它 Python 侧(如
decision_engine_demo.py)接入统一接口的桥梁。

约定: 跨项目传输一律 canonical(经纬度 WGS84 + 海拔 MSL + snake_case)。
坐标换算公式与 flycontrol/engines/geometry.py 完全一致(见 shared/contract.md)。

本模块不依赖 flycontrol 内部包, 可独立使用。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.1"
FRAME = "WGS84"
ALTITUDE_REF = "MSL"
M_PER_DEG_LAT = 111320.0


# ------------------------------------------------------------------ 工具
def _get(obj, key: str, default=None):
    """兼容 dict 与对象(属性)两种取值。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def meters_per_deg_lon(lat_deg: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def make_geo(ref_lat: float, ref_lon: float, ref_alt: float):
    """构造经纬度<->ENU 双向转换器(与 geometry.make_converter 等价)。"""
    mpdl = meters_per_deg_lon(ref_lat)

    def to_enu(lat: float, lon: float, alt_msl: float) -> Tuple[float, float, float]:
        x = (lon - ref_lon) * mpdl
        y = (lat - ref_lat) * M_PER_DEG_LAT
        z = alt_msl - ref_alt
        return x, y, z

    def to_latlon(x: float, y: float, z_agl: float) -> Tuple[float, float, float]:
        lon = ref_lon + x / mpdl
        lat = ref_lat + y / M_PER_DEG_LAT
        alt = ref_alt + z_agl
        return lat, lon, alt

    return to_enu, to_latlon


def _r(n, d=1):
    return round(float(n), d)


# ------------------------------------------------------------------ canonical 构建
def canonical_airport(airport) -> dict:
    return {
        "code": _get(airport, "code", ""),
        "name": _get(airport, "name", ""),
        "lat": float(_get(airport, "lat", 0.0)),
        "lon": float(_get(airport, "lon", 0.0)),
        "elevation": float(_get(airport, "elevation", 0.0)),
        "safe_radius": float(_get(airport, "safe_radius", 500.0)),
        "runway_heading": float(_get(airport, "runway_heading", 0.0)),
    }


def canonical_obstacle(o, to_latlon: Callable, elevation: float) -> dict:
    """flycontrol 障碍物(ENU + AGL) -> canonical(经纬度 + MSL)。"""
    x = float(_get(o, "x", 0.0))
    y = float(_get(o, "y", 0.0))
    lat, lon, _ = to_latlon(x, y, 0.0)
    obs_type = _get(o, "obs_type", 1)
    return {
        "id": str(_get(o, "id", "")),
        "name": _get(o, "name", ""),
        "type": "dynamic" if int(obs_type) == 2 else "fixed",
        "lat": _r(lat, 7),
        "lon": _r(lon, 7),
        "base_msl": _r(elevation + float(_get(o, "base_agl", 0.0))),
        "top_msl": _r(elevation + float(_get(o, "top_agl", 0.0))),
        "radius": float(_get(o, "radius", 30.0)),
        "buffer": float(_get(o, "buffer", 60.0)),
        "active": bool(_get(o, "active", True)),
    }


def canonical_airspace(a, to_latlon: Callable, elevation: float) -> dict:
    poly = _get(a, "polygon", []) or []
    poly_ll = []
    for (x, y) in poly:
        lat, lon, _ = to_latlon(float(x), float(y), 0.0)
        poly_ll.append([_r(lat, 7), _r(lon, 7)])
    return {
        "id": str(_get(a, "id", "")),
        "name": _get(a, "name", ""),
        "polygon": poly_ll,
        "floor_msl": _r(elevation + float(_get(a, "floor_agl", 0.0))),
        "ceiling_msl": _r(elevation + float(_get(a, "ceiling_agl", 0.0))),
        "active": bool(_get(a, "active", True)),
    }


def canonical_meteo(m) -> dict:
    return {
        "timestamp": _get(m, "timestamp", None) or datetime.now(timezone.utc).isoformat(),
        "wind_speed": float(_get(m, "wind_speed", 0.0)),
        "wind_dir": float(_get(m, "wind_dir", 0.0)),
        "gust": float(_get(m, "gust", 0.0)),
        "visibility": float(_get(m, "visibility", 0.0)),
        "cloud_base_agl": float(_get(m, "cloud_base", _get(m, "cloud_base_agl", 0.0))),
        "turbulence": int(_get(m, "turbulence", 1)),
        "wind_shear": int(_get(m, "wind_shear", 1)),
        "temperature": float(_get(m, "temperature", 0.0)),
        "dew_point": float(_get(m, "dew_point", 0.0)),
        "pressure": float(_get(m, "pressure", 1013.0)),
    }


def canonical_program(prog, to_latlon: Callable, elevation: float) -> Optional[dict]:
    if prog is None:
        return None
    wps = _get(prog, "waypoints", []) or []

    def wp(w) -> dict:
        lat, lon, alt = to_latlon(float(_get(w, "x", 0.0)), float(_get(w, "y", 0.0)),
                                  float(_get(w, "z", 0.0)))
        return {"lat": _r(lat, 7), "lon": _r(lon, 7), "alt_msl": _r(alt),
                "speed": float(_get(w, "speed", 0.0))}

    miss = _get(prog, "miss_approach", []) or []
    return {
        "type": _get(prog, "program_type", _get(prog, "type", "arrival")),
        "version": _get(prog, "version", "v0"),
        "source": _get(prog, "source", "dynamic"),
        "plan_id": int(_get(prog, "plan_id", 0)),
        "direction": _get(prog, "direction", None),
        "std_name": _get(prog, "std_name", None),
        "waypoints": [wp(w) for w in wps],
        "miss_approach": [wp(w) for w in miss],
    }


def canonical_traffic(item, to_latlon: Callable, elevation: float) -> dict:
    """canonical 交通项; 输入可为经纬度(canonical)或 ENU(需转换)。"""
    if _get(item, "lat", None) is not None and _get(item, "lon", None) is not None:
        lat = float(_get(item, "lat"))
        lon = float(_get(item, "lon"))
        alt_msl = float(_get(item, "alt_msl", elevation))
    else:
        lat, lon, alt_msl = to_latlon(float(_get(item, "x", 0.0)),
                                      float(_get(item, "y", 0.0)),
                                      float(_get(item, "alt", _get(item, "z", 0.0))))
        alt_msl = elevation + float(_get(item, "alt", 0.0))
    return {
        "id": str(_get(item, "id", "")),
        "model": _get(item, "model", ""),
        "reg_no": _get(item, "reg_no", _get(item, "regNo", "")),
        "ua_id": _get(item, "ua_id", _get(item, "uaId", "")),
        "phase": _get(item, "phase", "CRUISE"),
        "lat": _r(lat, 7),
        "lon": _r(lon, 7),
        "alt_msl": _r(alt_msl),
        "speed": float(_get(item, "speed", 0.0)),
        "heading": float(_get(item, "heading", 0.0)),
        "vertical_speed": float(_get(item, "vertical_speed", _get(item, "vs", 0.0))),
        "battery_pct": int(_get(item, "battery_pct", _get(item, "battery", 0))),
        "link_quality": int(_get(item, "link_quality", _get(item, "linkQuality", 5))),
        "emergency": bool(_get(item, "emergency", False)),
        "rid_lost": bool(_get(item, "rid_lost", _get(item, "ridLost", False))),
        "route": _get(item, "route", []),
    }


def canonical_snapshot(airport, obstacles, airspaces, meteo, program, traffic,
                       to_latlon: Callable, elevation: float,
                       generated_at: Optional[str] = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "frame": FRAME,
        "altitude_ref": ALTITUDE_REF,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "airport": canonical_airport(airport),
        "obstacles": [canonical_obstacle(o, to_latlon, elevation) for o in (obstacles or [])],
        "airspaces": [canonical_airspace(a, to_latlon, elevation) for a in (airspaces or [])],
        "meteo": canonical_meteo(meteo),
        "program": canonical_program(program, to_latlon, elevation),
        "traffic": [canonical_traffic(t, to_latlon, elevation) for t in (traffic or [])],
    }


# ------------------------------------------------------------------ 报文解析
def normalize_traffic_payload(body) -> List[dict]:
    """把 /api/traffic/ingest 的请求体归一化为 canonical traffic 列表。

    支持三种形式:
      1) 数组            [ {traffic}, ... ]
      2) 单个对象         {traffic}
      3) 消息信封         {messageHeader:{...}, payload:{traffic:[...]}}
    """
    if body is None:
        return []
    if isinstance(body, list):
        return list(body)
    if isinstance(body, dict):
        if "payload" in body and isinstance(body.get("payload"), dict):
            inner = body["payload"].get("traffic")
            if isinstance(inner, list):
                return list(inner)
            if isinstance(inner, dict):
                return [inner]
            return []
        # 单个对象, 若含 id/phase 视为一条交通
        if any(k in body for k in ("id", "phase", "ua_id", "reg_no")):
            return [body]
    return []


DEFAULT_SOURCE_NODE = "LOCAL"
DEFAULT_QUALITY = 0.6
TRACK_ID_KEYS = ("ua_id", "reg_no", "id")


def normalize_traffic_record(rec: dict, now_iso: Optional[str] = None,
                             source_node: Optional[str] = None,
                             quality: Optional[float] = None) -> dict:
    """补齐 v1.1 新增的交通字段（ts / source_node / quality / msg_id）。

    只做"补缺"，不覆盖上报方给出的值；因此老客户端（只发 3.5 的基础字段）
    依旧可用，服务端会自动补成合法记录。
    """
    out = dict(rec or {})
    if not out.get("ts"):
        out["ts"] = now_iso or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not out.get("source_node"):
        out["source_node"] = source_node or DEFAULT_SOURCE_NODE
    if out.get("quality") is None:
        out["quality"] = float(quality) if quality is not None else DEFAULT_QUALITY
    if not out.get("msg_id"):
        raw = "|".join(str(out.get(k, "")) for k in TRACK_ID_KEYS)
        raw += "|%s|%.6f|%.6f" % (out.get("ts"), float(out.get("lat", 0.0)),
                                  float(out.get("lon", 0.0)))
        import hashlib
        out["msg_id"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return out


def traffic_to_enu(items: Sequence[dict], to_enu: Callable) -> List[dict]:
    """canonical traffic -> 本地 ENU 字典(供后端存储/渲染)。"""
    out = []
    for it in items:
        lat = float(it.get("lat", 0.0))
        lon = float(it.get("lon", 0.0))
        alt = float(it.get("alt_msl", 0.0))
        x, y, z = to_enu(lat, lon, alt)
        rec = dict(it)
        rec.update({"x": _r(x), "y": _r(y), "alt": _r(z)})
        out.append(rec)
    return out
