"""Transactional advisory archive for a deployment on one host."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone


class AdvisoryArchive:
    def __init__(self, path, retention_days):
        if not 1 <= retention_days <= 36500:
            raise ValueError("invalid archive retention")
        self.path = path
        self.retention_days = retention_days

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def append(self, kind, record):
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        assessment_id = record.get("assessment_id")
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS advisory_records (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, assessment_id TEXT, saved_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS advisory_lookup ON advisory_records(kind, assessment_id, id)")
            db.execute("DELETE FROM advisory_records WHERE saved_at < ? OR (kind = 'review' AND assessment_id IN (SELECT assessment_id FROM advisory_records WHERE kind = 'snapshot' AND saved_at < ?))", (cutoff, cutoff))
            if kind == "review" and not db.execute("SELECT 1 FROM advisory_records WHERE kind = 'snapshot' AND assessment_id = ?", (assessment_id,)).fetchone():
                raise LookupError("assessment expired")
            db.execute("INSERT INTO advisory_records(kind, assessment_id, saved_at, payload) VALUES (?, ?, ?, ?)",
                       (kind, assessment_id, now.isoformat(), json.dumps(record, ensure_ascii=False, allow_nan=False)))

    def read(self, kind, limit=1, assessment_id=None):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        with closing(self.connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'advisory_records'").fetchone():
                return []
            rows = db.execute("""SELECT r.payload FROM advisory_records r
                WHERE r.kind = ? AND r.saved_at >= ? AND (? IS NULL OR r.assessment_id = ?)
                AND (r.kind != 'review' OR EXISTS (SELECT 1 FROM advisory_records s
                     WHERE s.kind = 'snapshot' AND s.assessment_id = r.assessment_id AND s.saved_at >= ?))
                ORDER BY r.id DESC LIMIT ?""", (kind, cutoff, assessment_id, assessment_id, cutoff, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]
