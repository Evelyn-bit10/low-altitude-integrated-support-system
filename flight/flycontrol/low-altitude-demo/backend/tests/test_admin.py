# -*- coding: utf-8 -*-
"""运维接口：指标 / 设备台账 / 路线管理 / RBAC。"""
from __future__ import annotations

import json
import os

import pytest

from app.routers import admin
from app.services import auth
from app.services.metrics import METRICS
from app.config import Settings


def test_metrics_accumulate():
    METRICS.inc("matched", 3)
    METRICS.observe_frame(1.5, 10, 7, 7, 100.0)
    snap = METRICS.snapshot()
    assert snap["frames"] >= 1
    assert snap["frame_ms"]["p50"] > 0
    assert snap["counters"].get("matched", 0) >= 3


def test_metrics_endpoint_shape():
    from app.routers.admin import metrics
    req = type("R", (), {"app": type("A", (), {"state": type("S", (), {"traffic": None})()})()})()
    out = metrics(req)
    assert "metrics" in out and "avg_frame_ms" in out["metrics"]


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_DATA_DIR", str(tmp_path))
    return tmp_path


def test_device_crud(tmp_data):
    d = admin.create_device(admin.Device(name="A站", source_key="A-RID", sigma_m=12.0))
    assert d["ok"] and d["device"]["id"].startswith("DEV-")
    assert len(admin.list_devices()["devices"]) == 1

    # 重复 source_key 应拒绝
    with pytest.raises(Exception):
        admin.create_device(admin.Device(name="dup", source_key="A-RID"))

    dev_id = d["device"]["id"]
    admin.update_device(dev_id, admin.Device(name="A站2", source_key="A-RID", sigma_m=15.0))
    assert admin.list_devices()["devices"][0]["name"] == "A站2"

    admin.delete_device(dev_id)
    assert admin.list_devices()["devices"] == []

    # 落盘文件存在
    assert os.path.exists(tmp_data / "devices.json")


def test_route_crud(tmp_data):
    r = admin.create_route(admin.Route(name="北向走廊", points=[
        admin.RoutePoint(x=0, y=0, z=0), admin.RoutePoint(x=0, y=2500, z=250)]))
    assert r["ok"]
    rid = r["route"]["id"]
    assert len(admin.list_routes()["routes"]) == 1
    admin.delete_route(rid)
    assert admin.list_routes()["routes"] == []


def test_rbac_matrix():
    assert auth.required_role("/api/metrics", "GET") is None       # 读不需要
    assert auth.required_role("/api/traffic/ingest", "POST") == "operator"
    assert auth.required_role("/api/devices", "POST") == "admin"
    assert auth.allow(auth.role_of("demo-viewer"), "viewer")
    assert not auth.allow(auth.role_of("demo-viewer"), "operator")
    assert auth.allow(auth.role_of("demo-admin"), "admin")
    assert not auth.allow(None, "operator")


def test_invalid_custom_tokens_do_not_enable_demo_tokens(monkeypatch):
    monkeypatch.setenv("DEMO_TOKENS", "invalid,unused:unknown")
    assert auth._load_tokens() == {}


def test_rbac_failure_denies_request(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    def fail(*args):
        raise RuntimeError("permission check failed")

    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setitem(app.state._state, "auth_enabled", True)
    monkeypatch.setattr(auth, "required_role", fail)
    client = TestClient(app)
    response = client.post("/api/ai/advice", json={"message": "review"})
    assert response.status_code == 503
    assert response.json() == {"detail": "权限检查失败"}
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["reason"] == "auth_check_failed"
    assert record["endpoint"] == "ai/advice"
    assert "permission check failed" not in json.dumps(record)


def test_ai_auth_denials_are_audited(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(path))
    monkeypatch.setitem(app.state._state, "auth_enabled", True)
    monkeypatch.setattr(auth, "TOKENS", {"viewer-secret": "viewer", "admin-secret": "admin"})
    client = TestClient(app)
    assert client.post("/api/ai/advice", headers={"X-Token": "viewer-secret"}, json={"message": "private body"}).status_code == 403
    assert client.get("/api/ai/audit", headers={"X-Token": "bad-secret"}).status_code == 401
    response = client.get("/api/ai/audit", headers={"X-Token": "admin-secret"})
    assert response.status_code == 200
    records = response.json()["records"]
    assert [(r["endpoint"], r["status"]) for r in records] == [("ai/audit", 401), ("ai/advice", 403)]
    data = path.read_text(encoding="utf-8")
    assert all(value not in data for value in ("viewer-secret", "bad-secret", "admin-secret", "private body"))


def test_ledger_feeds_engine(tmp_data, monkeypatch):
    """台账里的 σ 必须真的进入去重引擎（否则台账就是摆设）。"""
    from app.services import ledger
    monkeypatch.setattr(ledger, "DATA_DIR", str(tmp_data))
    admin._save("devices.json", [
        {"id": "DEV-1", "name": "A", "source_key": "A-RID", "sigma_m": 9.0, "status": "online"},
        {"id": "DEV-2", "name": "B", "source_key": "B-RID", "sigma_m": 25.0, "status": "offline"},
    ])
    sig = ledger.device_sigmas()
    assert sig == {"A-RID": 9.0}          # 离线的要排除

    from app.routers.traffic import TrafficStore
    from app.config import Settings
    st = Settings(database_url="sqlite://", dispatch_interval=5.0, auth_enabled=False,
                  dedup_source_sigmas={"A-RID": 30.0, "C-RID": 11.0})
    store = TrafficStore(st)
    assert store.engine.sigma_of("A-RID") == 9.0     # 台账覆盖配置
    assert store.engine.sigma_of("C-RID") == 11.0    # 台账没登记，保留配置


def test_no_fly_route_becomes_airspace(tmp_data, monkeypatch):
    """路线管理里 kind=no_fly 的区域要参与规划（能被 compliance/simulate 看到）。"""
    from app.services import ledger
    monkeypatch.setattr(ledger, "DATA_DIR", str(tmp_data))
    admin._save("routes.json", [{
        "id": "RTE-abc123", "name": "测试禁飞区", "kind": "no_fly",
        "points": [{"x": -1000, "y": 600}, {"x": -400, "y": 600},
                   {"x": -400, "y": 1400}, {"x": -1000, "y": 1400}],
        "floor_agl": 0.0, "ceiling_agl": 300.0,
    }])
    air = ledger.route_airspaces()
    assert len(air) == 1 and air[0].name == "测试禁飞区"
    assert len(air[0].polygon) == 4

    from app.store import Store
    snap = Store(Settings(database_url="sqlite://", dispatch_interval=5.0, auth_enabled=False)).snapshot()
    assert any(a.name == "测试禁飞区" for a in snap.airspaces)
