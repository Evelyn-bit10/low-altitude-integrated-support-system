# -*- coding: utf-8 -*-
"""态势历史存储测试。"""
import time

from app.services.history import HistoryStore


def _store(tmp_path):
    return HistoryStore(str(tmp_path / "history.db"), retention_hours=1, flush_sec=0.2)


def test_record_and_query(tmp_path):
    history = _store(tmp_path)
    now = time.time()
    history.record([{
        "id": "A", "lat": 30.0, "lon": 120.0, "alt_msl": 100,
        "speed": 10, "heading": 90, "battery_pct": 80, "phase": "APPROACH",
    }], now)
    history.flush_now()

    recent = history.recent(60, 10)
    assert recent["count"] == 1
    assert recent["tracks"][0]["id"] == "A"

    summary = history.summary(60, 60)
    assert summary["samples"] == 1
    assert summary["unique_tracks"] == 1
    history.close()


def test_prune_removes_old_rows(tmp_path):
    history = _store(tmp_path)
    history.record([{"id": "old"}], time.time() - 7200)
    history.flush_now()
    assert history.stats()["rows"] == 1

    history.prune()
    assert history.stats()["rows"] == 0
    history.close()


def test_summary_buckets(tmp_path):
    history = _store(tmp_path)
    base = time.time() - 120
    for i in range(3):
        history.record([{"id": "A"}, {"id": "B"}], base + i * 10)
    history.flush_now()

    summary = history.summary(60, 60)
    assert summary["samples"] >= 6
    assert summary["unique_tracks"] == 2
    history.close()


def test_empty_history(tmp_path):
    history = _store(tmp_path)
    assert history.recent(60, 10)["count"] == 0
    assert history.summary(60, 60)["samples"] == 0
    history.close()
