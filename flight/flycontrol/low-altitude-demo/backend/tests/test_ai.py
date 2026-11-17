import io
from copy import deepcopy
import json
from urllib.error import HTTPError, URLError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ai
from app.services.auth import required_role
from app.config import Settings
from app.store import Store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "_CONFIG_FILE", tmp_path / ".env.deepseek")


@pytest.fixture
def client():
    app = FastAPI()
    app.state.store = Store(Settings.from_env())
    app.include_router(ai.router, prefix="/api")
    return TestClient(app)


def test_missing_key_and_invalid_input(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert client.post("/api/ai/advice", json={"message": "hello"}).status_code == 503
    assert client.post("/api/ai/advice", json={"message": "  "}).status_code == 422
    assert client.post("/api/ai/advice", json={"message": "x" * 4001}).status_code == 422
    assert required_role("/api/ai/advice", "POST") == "operator"


def test_success_sends_context(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    def fake_open(request, timeout):
        body = json.loads(request.data)
        assert request.full_url == ai._ENDPOINT
        assert request.get_header("Authorization") == "Bearer secret"
        assert timeout == 30
        assert body["model"] == "deepseek-flash"
        user_data = json.loads(body["messages"][1]["content"])
        assert user_data["question"] == "巡检"
        assert user_data["context"]["data_freshness"] == "unknown"
        assert len(user_data["context"]["candidates"]) == 8
        assert len(body["messages"]) == 2
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "先确认空域"}, "finish_reason": "stop"}]}).encode())
    monkeypatch.setattr(ai, "urlopen", fake_open)
    response = client.post("/api/ai/advice", json={"message": "巡检"})
    assert response.status_code == 200
    result = response.json()
    assert result["advice"] == "先确认空域"
    assert result["model"] == "deepseek-flash"
    assert result["requires_human_review"] is True
    assert result["validated"] is False and result["executed"] is False
    assert result["context"]["data_freshness"] == "unknown"


@pytest.mark.parametrize("error,status", [
    (HTTPError("https://example.com", 429, "limit", {}, None), 503),
    (HTTPError("https://example.com", 401, "secret", {}, None), 502),
    (URLError("offline"), 502),
    (TimeoutError(), 504),
])
def test_upstream_error(client, monkeypatch, error, status):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(ai, "urlopen", fail)
    response = client.post("/api/ai/advice", json={"message": "hello"})
    assert response.status_code == status
    assert "secret" not in response.text


def test_file_configuration_and_environment_override(client, monkeypatch):
    ai._CONFIG_FILE.write_text(json.dumps({"api_key": "file-key", "model": "file-model"}), encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    def fake_open(request, timeout):
        assert request.get_header("Authorization") == "Bearer " + expected[0]
        assert json.loads(request.data)["model"] == expected[1]
        return io.BytesIO(b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}')
    monkeypatch.setattr(ai, "urlopen", fake_open)
    expected = ["file-key", "file-model"]
    assert client.post("/api/ai/advice", json={"message": "hi"}).status_code == 200
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    expected[:] = ["env-key", "env-model"]
    assert client.post("/api/ai/advice", json={"message": "hi"}).status_code == 200
    ai._CONFIG_FILE.write_text("{", encoding="utf-8")
    assert client.post("/api/ai/advice", json={"message": "hi"}).status_code == 503


def test_rejects_incomplete_response(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr(ai, "urlopen", lambda *a, **k: io.BytesIO(b'{"choices":[{"message":{"content":"partial"},"finish_reason":"length"}]}'))
    assert client.post("/api/ai/advice", json={"message": "hello"}).status_code == 502


@pytest.mark.parametrize("program_type", ["arrival", "departure"])
def test_context_does_not_modify_store(client, monkeypatch, program_type):
    store = client.app.state.store
    before = deepcopy(store.__dict__)
    monkeypatch.setattr(store, "publish", lambda *args: pytest.fail("unexpected publish"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr(ai, "urlopen", lambda *a, **k: io.BytesIO(
        b'{"choices":[{"message":{"content":"review"},"finish_reason":"stop"}]}'))
    response = client.post("/api/ai/advice", json={"message": "review", "program_type": program_type})
    assert response.status_code == 200, response.text
    after = dict(store.__dict__)
    after.pop("publish")
    assert after == before
    context = response.json()["context"]
    assert context["program_type"] == program_type
    assert context["risk"] is None
    assert len(context["candidates"]) == 8
    assert context["limitations"]


def test_context_failure_does_not_call_upstream(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    def fail(*args):
        raise ValueError("internal data")
    monkeypatch.setattr(ai, "build_context", fail)
    monkeypatch.setattr(ai, "urlopen", lambda *args, **kwargs: pytest.fail("unexpected upstream call"))
    response = client.post("/api/ai/advice", json={"message": "review"})
    assert response.status_code == 503
    assert "internal data" not in response.text


def test_no_available_candidates_is_reported(client, monkeypatch):
    monkeypatch.setattr(ai, "rank_candidates", lambda *args: [
        {"direction": "N", "available": False, "score": 0, "reasons": [], "metrics": {}}])
    context = ai.build_context(client.app.state.store, "arrival")
    assert any("没有可用候选" in item for item in context["limitations"])
    assert context["data_freshness"] == "unknown"
