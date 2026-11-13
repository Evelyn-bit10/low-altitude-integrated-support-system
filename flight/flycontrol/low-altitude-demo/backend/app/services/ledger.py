# -*- coding: utf-8 -*-
"""把"设备台账"和"路线管理"里维护的数据接进运行引擎。

为什么要这一层
--------------
台账/路线如果只在接口里存着、不参与算法，那就是摆设：
改了设备的 σ、加了一条禁飞区，去重和规划却毫无变化，验收一问就露馅。

这个模块负责把两份 JSON 翻译成引擎认识的东西：
    * 设备台账  -> {source_key: sigma_m}      （作为去重的观测噪声 R）
    * 路线      -> List[Airspace]             （kind == "no_fly" 的转成限制空域）
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

log = logging.getLogger(__name__)

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("DEMO_DATA_DIR", os.path.join(_BACKEND, "data"))


def _load(name: str, default):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def device_sigmas() -> Dict[str, float]:
    """台账里登记的 source_key -> σ（米）。台账为空时返回空字典。"""
    out: Dict[str, float] = {}
    for d in _load("devices.json", []):
        key = (d.get("source_key") or "").strip()
        if not key or d.get("status") == "offline":
            continue
        try:
            out[key] = float(d.get("sigma_m") or 20.0)
        except (TypeError, ValueError):
            continue
    return out


def route_airspaces():
    """把 kind == "no_fly" 的路线转成限制空域（其余类型暂不参与规划）。"""
    from app.domain import Airspace

    out: List[Airspace] = []
    for r in _load("routes.json", []):
        if r.get("kind") != "no_fly":
            continue
        pts = [(float(p["x"]), float(p["y"])) for p in (r.get("points") or [])
               if isinstance(p, dict) and "x" in p and "y" in p]
        if len(pts) < 3:
            continue
        out.append(Airspace(
            id=int(r.get("id", "0").replace("RTE-", "")[:6], 16) if str(r.get("id", "")).startswith("RTE-") else 0,
            name=r.get("name") or "自定义禁飞区",
            polygon=pts,
            floor_agl=float(r.get("floor_agl") or 0.0),
            ceiling_agl=float(r.get("ceiling_agl") or 300.0),
        ))
    return out
