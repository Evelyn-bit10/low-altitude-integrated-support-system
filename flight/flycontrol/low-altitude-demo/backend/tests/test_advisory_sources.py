import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.routers import ai
from app.services.advisory_sources import assess_sources
from app.store import Store


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
    monkeypatch.delenv("ADVISORY_MAX_AGE_SECONDS", raising=False)
    assert assess_sources(metadata(now), now)[0] == "unknown"
    monkeypatch.setenv("ADVISORY_MAX_AGE_SECONDS", "60")
    data = metadata(now)
    del data["meteo"]["observed_at"]
    assert assess_sources(data, now)[0] == "unknown"


@pytest.mark.parametrize("mode", ["missing", "stale", "future", "untrusted"])
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
            offset = {"stale": -120, "future": 10, "untrusted": 0}[mode]
            env.advisory_sources = metadata(datetime.now(timezone.utc) + timedelta(seconds=offset), mode != "untrusted")
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
