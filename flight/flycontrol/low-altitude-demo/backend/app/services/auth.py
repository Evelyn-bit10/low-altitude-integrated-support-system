# -*- coding: utf-8 -*-
"""轻量 RBAC：Token -> 角色 -> 权限。

演示阶段默认关闭（`auth_enabled=False`），开启后所有**写操作**都要带 token。

角色
----
    viewer   : 只读（GET）
    operator : 读 + 业务写（推程序、开关去重、发推送）
    admin    : 全部，含设备台账/路线管理/影子模式开关

Token 来源（按优先级）
----------------------
    1. 环境变量 `DEMO_TOKENS`，形如  `admin-token:admin,op-token:operator,view-token:viewer`
    2. 默认内置三个演示 token（见 _DEFAULT_TOKENS），方便评审直接试
"""
from __future__ import annotations

import os
from typing import Dict, Optional

ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}

_DEFAULT_TOKENS = {
    "demo-viewer": "viewer",
    "demo-operator": "operator",
    "demo-admin": "admin",
}


def _load_tokens() -> Dict[str, str]:
    raw = os.environ.get("DEMO_TOKENS", "").strip()
    if not raw:
        return dict(_DEFAULT_TOKENS)
    out: Dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        tok, role = item.rsplit(":", 1)
        if role in ROLE_LEVEL:
            out[tok.strip()] = role
    return out or dict(_DEFAULT_TOKENS)


TOKENS = _load_tokens()

# 写操作最低角色要求（按路径前缀匹配，长的优先）
RULES = [
    ("/api/devices", "admin"),
    ("/api/routes", "admin"),
    ("/api/traffic/shadow", "admin"),
    ("/api/traffic/reset", "admin"),
    ("/api/env/", "operator"),
    ("/api/program/", "operator"),
    ("/api/push/", "operator"),
    ("/api/traffic/ingest", "operator"),
]


def role_of(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return TOKENS.get(token.strip())


def required_role(path: str, method: str) -> Optional[str]:
    """返回该请求要求的最低角色；None 表示不需要鉴权。"""
    if method in ("GET", "HEAD", "OPTIONS"):
        return None
    for prefix, role in RULES:
        if path.startswith(prefix):
            return role
    return "operator"


def allow(role: Optional[str], need: Optional[str]) -> bool:
    if need is None:
        return True
    if role is None:
        return False
    return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL.get(need, 99)
