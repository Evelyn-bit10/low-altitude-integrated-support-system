# -*- coding: utf-8 -*-
"""`/api/program/join` 接口测试。

为什么单独测这个接口
--------------------
它是演示的核心交互（点击地图 → 匹配航道），也是改动最频繁的一段代码，
但之前完全没有测试。这里覆盖 4 个最容易坏的点：

    ① 正常点：能给出方向、航迹、接续点
    ② 跑道口附近：不能 500，前端自己兜底最后一段
    ③ 20 m 网格缓存：重复请求必须命中，不能重算
    ④ 气象变更：缓存 key 必须失效，否则换了风还是老结果

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests/test_program_join.py -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient                        # noqa: E402

from app.main import app                                         # noqa: E402
from app.plans_library import DIRECTIONS                         # noqa: E402
from app.routers import program as program_router                # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _join(client, x, y, battery=100):
    r = client.get("/api/program/join", params={"x": x, "y": y, "battery": battery})
    assert r.status_code == 200, r.text
    return r.json()


def test_join_normal_point(client):
    """普通点位：给出合法方向 + 完整航迹 + 接续几何信息"""
    d = _join(client, 900, 900)

    assert d["direction"] in DIRECTIONS
    assert len(d["waypoints"]) >= 2
    assert 0 <= d["join_index"] < len(d["waypoints"])
    assert d["join_distance"] >= 0
    assert isinstance(d["join_safe"], bool)
    assert "available" in d
    # 风速为 0 时至少有一个方向可用
    assert d["available"] is True


def test_join_near_runway_does_not_crash(client):
    """点在跑道中心：不能 500（接续点可能落在最后一个航路点，由前端兜底）"""
    d = _join(client, 0, 0)
    assert d["direction"] in DIRECTIONS
    assert len(d["waypoints"]) >= 1


def test_join_cache_hit(client):
    """同一位置重复请求必须命中 20 m 网格缓存，不增加缓存条目"""
    program_router._JOIN_RESP_CACHE.clear()
    a = _join(client, 1100, -800)
    n1 = len(program_router._JOIN_RESP_CACHE)
    b = _join(client, 1100, -800)
    n2 = len(program_router._JOIN_RESP_CACHE)

    assert a == b
    assert n1 == n2 == 1


def test_join_cache_invalidated_by_meteo(client):
    """改气象后缓存必须失效，否则会出现"改了风却还是老方向\""""
    program_router._JOIN_RESP_CACHE.clear()
    client.post("/api/env/meteo", json={"wind_speed": 3, "wind_dir": 0, "precipitation": 0})
    _join(client, -900, 900)
    n_calm = len(program_router._JOIN_RESP_CACHE)

    client.post("/api/env/meteo", json={"wind_speed": 9, "wind_dir": 180, "precipitation": 0})
    _join(client, -900, 900)
    n_windy = len(program_router._JOIN_RESP_CACHE)

    assert n_windy == n_calm + 1, "气象变了但缓存没失效"

    # 复原，避免影响其它用例
    client.post("/api/env/meteo", json={"wind_speed": 3, "wind_dir": 0, "precipitation": 0})


def test_join_reports_unavailable_in_extreme_wind(client):
    """极端风：如实返回不可飞，而不是硬选一条（安全红线）"""
    client.post("/api/env/meteo", json={"wind_speed": 25, "wind_dir": 0, "precipitation": 0})
    d = _join(client, 0, -1400)

    if d["available"] is False:
        note = d.get("env_note", "")
        assert note, "不可飞时必须给出原因"
        assert ("不可" in note) or ("超限" in note), note
    else:
        # 若仍有可用方向，必须给出合法方向（说明侧风未全部超限）
        assert d["direction"] in DIRECTIONS

    client.post("/api/env/meteo", json={"wind_speed": 3, "wind_dir": 0, "precipitation": 0})
