"""机位数据存储（默认机位 + 用户自定义机位，支持持久化）。"""

import json
import os
from typing import Dict, List, Any, Optional

from config_stands import DRONE_STANDS


_CUSTOM_STANDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "offline_data", "stands_custom.json")


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _normalize_stand(stand: Dict[str, Any]) -> Dict[str, Any]:
    """最小字段归一化，保证 UI/分配逻辑可用。"""
    stand_id = str(stand.get("id", "")).strip()
    name = str(stand.get("name", stand_id)).strip() or stand_id
    stand_type = stand.get("type", "outdoor")
    if stand_type not in ("indoor", "outdoor"):
        stand_type = "outdoor"
    priority = int(stand.get("priority", 1) or 1)
    if priority < 1:
        priority = 1
    features = stand.get("features") or []
    if not isinstance(features, list):
        features = []
    features = [str(x) for x in features]
    deleted = bool(stand.get("__deleted__", False))
    return {
        "id": stand_id,
        "name": name,
        "type": stand_type,
        "priority": priority,
        "description": str(stand.get("description", "") or ""),
        "features": features,
        "__deleted__": deleted,
    }


def _read_custom_stands() -> List[Dict[str, Any]]:
    if not os.path.exists(_CUSTOM_STANDS_FILE):
        return []
    try:
        with open(_CUSTOM_STANDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        result = []
        for s in data:
            if isinstance(s, dict):
                ns = _normalize_stand(s)
                if ns["id"]:
                    result.append(ns)
        return result
    except Exception:
        return []


def _write_custom_stands(stands: List[Dict[str, Any]]) -> None:
    _ensure_parent_dir(_CUSTOM_STANDS_FILE)
    with open(_CUSTOM_STANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(stands, f, ensure_ascii=False, indent=2)


def list_stands() -> List[Dict[str, Any]]:
    """返回合并后的机位列表：默认机位 + 自定义机位（自定义 id 覆盖默认）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for s in DRONE_STANDS:
        if isinstance(s, dict):
            ns = _normalize_stand(s)
            if ns["id"]:
                merged[ns["id"]] = ns
    for s in _read_custom_stands():
        merged[s["id"]] = s  # 覆盖默认 or 新增
    # 过滤掉被标记删除的机位（通常用于隐藏默认机位）
    return [v for v in merged.values() if not bool(v.get("__deleted__", False))]


def get_custom_stands() -> List[Dict[str, Any]]:
    return _read_custom_stands()


def add_or_update_custom_stand(stand: Dict[str, Any]) -> Dict[str, Any]:
    """新增/更新一条自定义机位（按 id 覆盖）。返回归一化后的 stand。"""
    ns = _normalize_stand(stand)
    if not ns["id"]:
        raise ValueError("stand id is empty")
    customs = _read_custom_stands()
    customs = [s for s in customs if str(s.get("id")) != ns["id"]]
    customs.append(ns)
    _write_custom_stands(customs)
    return ns


def delete_custom_stand(stand_id: str) -> bool:
    """仅删除自定义机位（不影响默认机位）。"""
    stand_id = str(stand_id).strip()
    customs = _read_custom_stands()
    new_customs = [s for s in customs if str(s.get("id")) != stand_id]
    if len(new_customs) == len(customs):
        return False
    _write_custom_stands(new_customs)
    return True


def mark_deleted(stand_id: str) -> None:
    """将某个机位标记为删除（用于隐藏默认机位）。"""
    stand_id = str(stand_id).strip()
    if not stand_id:
        raise ValueError("stand id is empty")
    customs = _read_custom_stands()
    customs = [s for s in customs if str(s.get("id")) != stand_id]
    customs.append({"id": stand_id, "__deleted__": True})
    _write_custom_stands(customs)


def is_default_stand(stand_id: str) -> bool:
    stand_id = str(stand_id).strip()
    for s in DRONE_STANDS:
        if isinstance(s, dict) and str(s.get("id")) == stand_id:
            return True
    return False

