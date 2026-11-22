from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.routers import ai, program
from app.services import weather_reference as weather
from app.store import Store


def payload(published, adcode="500108"):
    return {"status": "1", "lives": [{
        "adcode": adcode, "reporttime": published, "weather": "cloudy",
        "temperature": "18", "winddirection": "north", "windpower": "<3", "humidity": "54",
    }]}


def test_report_time_is_publication_not_observation():
    now = datetime(2026, 11, 21, 8, 30, tzinfo=timezone.utc)
    record = weather._parse(payload("2026-11-21 16:03:25"), "500108", now)
    assert record["published_at"] == "2026-11-21T16:03:25+08:00"
    assert record["wind_power_level"] == "<3"
    assert "observed_at" not in record and "wind_speed" not in record
    with pytest.raises(ValueError):
        weather._parse(payload("2026-11-21 16:03:25", "110101"), "500108", now)
    with pytest.raises(ValueError):
        weather._parse(payload("2026-11-21 16:31:00"), "500108", now)


def test_reference_failure_and_stale_cache(monkeypatch):
    service = weather.WeatherReference()
    monkeypatch.setattr(weather, "_key", lambda: "")
    service.refresh()
    assert service.snapshot() == {"status": "unavailable", "reason": "not_configured", "data": None}
    now = datetime.now(timezone.utc)
    published = (now - timedelta(hours=4)).astimezone(weather._SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    service._record = weather._parse(payload(published), "500108", now)
    monkeypatch.setattr(weather, "_key", lambda: "test-key")
    def offline(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(weather, "urlopen", offline)
    service.refresh()
    assert service.snapshot()["status"] == "stale"
    assert service.snapshot()["reason"] == "fetch_failed"


def test_reference_endpoint_does_not_change_verdict(monkeypatch):
    monkeypatch.delenv("ADVISORY_SHOW_DEMO", raising=False)
    app = FastAPI()
    store = app.state.store = Store(Settings.from_env())
    service = store.weather_reference = weather.WeatherReference()
    now = datetime.now(timezone.utc)
    published = now.astimezone(weather._SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    service._record = weather._parse(payload(published), "500108", now)
    service._error = None
    app.include_router(program.router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/weather/reference")
    assert response.status_code == 200
    assert response.json()["status"] == "current"
    context = ai.build_context(store, "arrival")
    assert context["data_sources"]["meteo"]["status"] == "unknown"
    assert context["engine_verdict"]["code"] == "INSUFFICIENT_DATA"
