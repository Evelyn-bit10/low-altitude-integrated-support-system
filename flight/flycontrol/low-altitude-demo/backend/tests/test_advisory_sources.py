import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.routers import ai
from app.services.advisory_sources import assess_sources
from app.store import Store


@pytest.fixture(autouse=True)
def source_policy(monkeypatch):
    for name in ("METEO", "OBSTACLES", "AIRSPACE"):
        monkeypatch.setenv(f"ADVISORY_{name}_SOURCE", "adapter")
        monkeypatch.setenv(f"ADVISORY_{name}_MAX_AGE_SECONDS", "60")


def metadata(timestamp, trusted=True):
    return {name: {"source": "adapter", "observed_at": timestamp.isoformat(), "trusted": trusted}
            for name in ("meteo", "obstacles", "airspace")}


@pytest.mark.parametrize("offset,trusted,expected", [
    (-5, True, "fresh"), (-61, True, "stale"), (1, True, "future"),
    (-5, False, "unknown"),
])
def test_source_status(monkeypatch, offset, trusted, expected):
    monkeypatch.setenv("ADVISORY_MAX_AGE_SECONDS", "60")
    now = datetime.now(timezone.utc)
    result, _ = assess_sources(metadata(now + timedelta(seconds=offset), trusted), now)
    assert result == expected


def test_source_missing_timestamp_and_invalid_configuration(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.delenv("ADVISORY_METEO_MAX_AGE_SECONDS", raising=False)
    assert assess_sources(metadata(now), now)[0] == "unknown"
    monkeypatch.setenv("ADVISORY_METEO_MAX_AGE_SECONDS", "60")
    data = metadata(now)
    del data["meteo"]["observed_at"]
    assert assess_sources(data, now)[0] == "unknown"


def test_source_policy_is_independent_and_fails_closed(monkeypatch):
    now = datetime.now(timezone.utc)
    data = metadata(now - timedelta(seconds=30))
    monkeypatch.setenv("ADVISORY_METEO_MAX_AGE_SECONDS", "20")
    freshness, sources = assess_sources(data, now)
    assert freshness == "stale" and sources["meteo"]["status"] == "stale"
    assert sources["obstacles"]["status"] == "fresh"
    data["airspace"]["source"] = "other"
    assert assess_sources(data, now)[0] == "conflict"
    monkeypatch.delenv("ADVISORY_AIRSPACE_SOURCE")
    assert assess_sources(data, now)[1]["airspace"]["status"] == "unknown"


@pytest.mark.parametrize("mode", ["missing", "stale", "future", "untrusted", "conflict"])
def test_untrusted_snapshot_cannot_call_model(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("ADVISORY_MAX_AGE_SECONDS", "60")
    monkeypatch.delenv("ADVISORY_SHOW_DEMO", raising=False)
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(ai, "_CONFIG_FILE", tmp_path / "missing")
    monkeypatch.setattr(ai, "_call_model", lambda *a: pytest.fail("model called"))
    store = Store(Settings.from_env())
    original = store.snapshot
    def snapshot():
        env = original()
        if mode != "missing":
            offset = {"stale": -120, "future": 10, "untrusted": 0, "conflict": 0}[mode]
            env.advisory_sources = metadata(datetime.now(timezone.utc) + timedelta(seconds=offset), mode != "untrusted")
            if mode == "conflict":
                env.advisory_sources["meteo"]["source"] = "unapproved"
        return env
    monkeypatch.setattr(store, "snapshot", snapshot)
    monkeypatch.setattr(store, "publish", lambda *a: pytest.fail("publish called"))
    app = FastAPI()
    app.state.store = store
    app.include_router(ai.router, prefix="/api")
    client = TestClient(app)
    response = client.post("/api/ai/advice", json={"message": "test", "demo_only": True})
    assert response.status_code == 200
    body = response.json()
    assert body["refusal"]["code"] == "INSUFFICIENT_DATA"
    assert body["context"]["engine_verdict"]["recommended"] is None
    assert body["context"]["candidates"] == []
    assert body["context"]["demo_only"] is False
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["assessment_id"] == body["context"]["assessment_id"]
    assert client.get("/api/ai/verdict").json()["engine_verdict"]["recommended"] is None


def test_adapter_failure_never_falls_back_to_demo(monkeypatch, tmp_path):
    def unavailable():
        raise OSError("upstream unavailable")

    monkeypatch.setenv("ADVISORY_SHOW_DEMO", "1")
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("ADVISORY_SNAPSHOT_FILE", str(tmp_path / "snapshots.jsonl"))
    monkeypatch.setattr(ai, "_call_model", lambda *a: pytest.fail("model called"))
    store = Store(Settings.from_env())
    store.advisory_snapshot_provider = unavailable
    app = FastAPI()
    app.state.store = store
    app.include_router(ai.router, prefix="/api")
    body = TestClient(app).post("/api/ai/advice", json={"message": "test"}).json()
    assert body["conclusion"] == "INSUFFICIENT_DATA"
    assert body["context"]["data_freshness"] == "unavailable"
    assert body["context"]["candidates"] == []
    assert not body["context"]["demo_only"]


def test_demo_flag_is_server_only(monkeypatch, tmp_path):
    monkeypatch.setenv("ADVISORY_SHOW_DEMO", "1")
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(ai, "_call_model", lambda *a: pytest.fail("model called"))
    monkeypatch.setattr(ai, "rank_candidates", lambda *a: [{"direction": "S", "available": True, "score": 1, "metrics": {}, "reasons": []}])
    store = Store(Settings.from_env())
    app = FastAPI()
    app.state.store = store
    app.include_router(ai.router, prefix="/api")
    result = TestClient(app).post("/api/ai/advice", json={"message": "test"}).json()
    assert result["context"]["demo_only"] is True
    assert result["context"]["candidates"]
    assert result["context"]["engine_verdict"]["recommended"] is None
    assert result["refusal"]["code"] == "INSUFFICIENT_DATA"
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["assessment_id"] == result["context"]["assessment_id"]


@pytest.mark.parametrize("model_text,guarded", [("演示数据需要核验。", False), ("可以放行", True)])
def test_explicit_demo_model_call_does_not_change_verdict(monkeypatch, tmp_path, model_text, guarded):
    monkeypatch.setenv("ADVISORY_SHOW_DEMO", "1")
    monkeypatch.setenv("ADVISORY_DEMO_CALL_MODEL", "1")
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("ADVISORY_SNAPSHOT_FILE", str(tmp_path / "snapshots.jsonl"))
    monkeypatch.setattr(ai, "_config", lambda: ("test-key", "test-model"))
    monkeypatch.setattr(ai, "rank_candidates", lambda *a: [])
    seen = []
    def call_model(key, model, message, context):
        seen.append(context)
        return model_text, {}
    monkeypatch.setattr(ai, "_call_model", call_model)
    app = FastAPI()
    app.state.store = Store(Settings.from_env())
    app.include_router(ai.router, prefix="/api")
    result = TestClient(app).post("/api/ai/advice", json={"message": "解释演示场景"}).json()
    assert len(seen) == 1 and seen[0]["demo_only"] is True
    assert result["context"]["data_freshness"] == "unknown"
    assert result["conclusion"] == "INSUFFICIENT_DATA"
    assert result["context"]["engine_verdict"]["recommended"] is None
    assert result["validated"] is False and result["executed"] is False
    assert result["safety_guard"]["triggered"] is guarded
    assert result["advice"] == (None if guarded else model_text)
