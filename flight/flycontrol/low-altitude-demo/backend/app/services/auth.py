"""轻量 RBAC：Token -> 个人身份 + 角色 -> 权限。

演示阶段默认关闭（`auth_enabled=False`），开启后所有**写操作**都要带 token。

Token 来源（按优先级）
----------------------
    1. 环境变量 `DEMO_TOKENS`，形如 `admin-token:admin,op-token:operator`
    2. 环境变量 `DEMO_IDENTITIES`，形如 `admin-token:alice,op-token:bob`
    3. 默认内置三个演示 token；其身份为对应的 demo 用户。

身份标识不是从请求体中读取，而是由服务端令牌配置绑定。
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
_DEFAULT_IDENTITIES = {
    "demo-viewer": "demo-viewer",
    "demo-operator": "demo-operator",
    "demo-admin": "demo-admin",
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
        if role in ROLE_LEVEL and tok.strip():
            out[tok.strip()] = role
    return out


def _load_identities() -> Dict[str, str]:
    raw = os.environ.get("DEMO_IDENTITIES", "").strip()
    if not raw:
        return dict(_DEFAULT_IDENTITIES)
    out: Dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        tok, identity = item.rsplit(":", 1)
        if tok.strip() and identity.strip():
            out[tok.strip()] = identity.strip()
    return out


TOKENS = _load_tokens()
IDENTITIES = _load_identities()

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


def identity_of(token: Optional[str]) -> Optional[str]:
    if not token or token.strip() not in TOKENS:
        return None
    return IDENTITIES.get(token.strip())


def required_role(path: str, method: str) -> Optional[str]:
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
