# -*- coding: utf-8 -*-
"""进离港排序的确定性测试。"""
from app.services.sequencing import sequence


def test_empty_input():
    result = sequence([])
    assert result["method"] == "empty"
    assert result["order"] == []


def test_single_flight_lands_at_eta():
    result = sequence([{"id": "A", "eta_sec": 60, "battery_pct": 80}])
    assert result["method"] == "exact"
    row = result["order"][0]
    assert row["land_at_sec"] == 60
    assert row["wait_sec"] == 0
    assert result["landed_count"] == 1


def test_second_flight_respects_separation():
    result = sequence([
        {"id": "A", "eta_sec": 0, "battery_pct": 90},
        {"id": "B", "eta_sec": 10, "battery_pct": 90},
    ], min_separation_sec=45)
    rows = {row["id"]: row for row in result["order"]}
    assert rows["B"]["wait_sec"] >= 35 - 1e-6


def test_emergency_wins_when_eta_equal():
    result = sequence([
        {"id": "A", "eta_sec": 0, "battery_pct": 90},
        {"id": "C", "eta_sec": 0, "battery_pct": 90, "emergency": True},
    ])
    assert result["order"][0]["id"] == "C"


def test_low_battery_flight_goes_first():
    result = sequence([
        {"id": "A", "eta_sec": 0, "battery_pct": 90},
        {"id": "B", "eta_sec": 5, "battery_pct": 3},
    ])
    assert result["order"][0]["id"] == "B"
    assert result["landed_count"] == 2


def test_depleted_flight_is_marked():
    result = sequence([
        {"id": "A", "eta_sec": 0, "battery_pct": 1},
        {"id": "B", "eta_sec": 0, "battery_pct": 1},
    ])
    assert result["landed_count"] == 1
    assert any(not row["landed"] for row in result["order"])


def test_large_set_uses_greedy():
    flights = [{"id": "F%d" % i, "eta_sec": i * 10, "battery_pct": 90 - i}
               for i in range(9)]
    result = sequence(flights)
    assert result["method"].startswith("greedy")
    assert result["landed_count"] >= 1


def test_slow_flight_saves_battery():
    flights = [
        {"id": "A", "eta_sec": 0, "battery_pct": 5},
        {"id": "B", "eta_sec": 0, "battery_pct": 90},
    ]
    slow = sequence(flights, slow_flight=True)
    spiral = sequence(flights, slow_flight=False)
    slow_b = next(r["battery_after_pct"] for r in slow["order"] if r["id"] == "B")
    spiral_b = next(r["battery_after_pct"] for r in spiral["order"] if r["id"] == "B")
    assert slow_b > spiral_b


def test_rationale_mentions_depleted():
    result = sequence([
        {"id": "A", "eta_sec": 0, "battery_pct": 1},
        {"id": "B", "eta_sec": 0, "battery_pct": 1},
    ])
    assert any("电量耗尽" in line for line in result["rationale"])
