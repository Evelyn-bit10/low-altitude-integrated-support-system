from contextlib import closing

import pytest

from app.services.advisory_archive import AdvisoryArchive


def test_archive_expiry_hides_and_removes_dependent_reviews(tmp_path):
    archive = AdvisoryArchive(tmp_path / "archive.db", 7)
    snapshot = {"assessment_id": "assessment", "context": {"code": "INSUFFICIENT_DATA"}}
    review = {"assessment_id": "assessment", "decision": "needs_more_info"}
    archive.append("snapshot", snapshot)
    archive.append("review", review)
    assert archive.read("snapshot", assessment_id="assessment") == [snapshot]
    assert archive.read("review") == [review]
    with closing(archive.connect()) as db, db:
        db.execute("UPDATE advisory_records SET saved_at = '2000-01-01' WHERE kind = 'snapshot'")
    assert archive.read("review") == []
    with pytest.raises(LookupError):
        archive.append("review", review)
    archive.append("audit", {"request_id": "request"})
    with closing(archive.connect()) as db:
        assert db.execute("SELECT kind FROM advisory_records").fetchall() == [("audit",)]


def test_archive_integrates_advice_and_review(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.routers import ai
    from app.services import auth
    from app.store import Store

    monkeypatch.setenv("ADVISORY_ARCHIVE_DB", str(tmp_path / "archive.db"))
    monkeypatch.setenv("ADVISORY_RETENTION_DAYS", "7")
    monkeypatch.delenv("ADVISORY_SHOW_DEMO", raising=False)
    monkeypatch.setattr(auth, "TOKENS", {"admin-secret": "admin"})
    monkeypatch.setattr(auth, "IDENTITIES", {"admin-secret": "person-1"})
    app = FastAPI()
    app.state.store = Store(Settings.from_env())
    app.state.auth_enabled = True
    app.include_router(ai.router, prefix="/api")
    client = TestClient(app)
    headers = {"X-Token": "admin-secret"}
    result = client.post("/api/ai/advice", headers=headers, json={"message": "review"}).json()
    assessment_id = result["context"]["assessment_id"]
    review = client.post("/api/ai/reviews", headers=headers, json={
        "assessment_id": assessment_id, "decision": "needs_more_info"}).json()["review"]
    replay = client.get("/api/ai/assessments/" + assessment_id, headers=headers).json()
    assert replay["reviews"] == [review]
    audit = client.get("/api/ai/audit", headers=headers).json()["records"]
    assert any(record.get("assessment_id") == assessment_id for record in audit)
    assert "admin-secret" not in str(audit)


def test_configured_archive_unavailable_does_not_fall_back(monkeypatch, tmp_path):
    from app.routers import ai

    monkeypatch.setenv("ADVISORY_ARCHIVE_DB", str(tmp_path / "missing" / "archive.db"))
    monkeypatch.setenv("ADVISORY_RETENTION_DAYS", "7")
    legacy = tmp_path / "legacy.jsonl"
    monkeypatch.setenv("ADVISORY_AUDIT_FILE", str(legacy))
    assert ai._append_audit({"request_id": "request"}) is False
    assert not legacy.exists()
