# -*- coding: utf-8 -*-
"""TrafficStore 集成测试：多设备上报 -> 去重 -> canonical 输出。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests/test_traffic_store.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings                      # noqa: E402
from app.routers.traffic import TrafficStore         # noqa: E402

LAT, LON = 30.0, 120.0
M2D = 1.0 / 111320.0
T0 = 1000.0


def make_settings(**kw) -> Settings:
    base = dict(database_url="sqlite://", dispatch_interval=2.0, auth_enabled=False,
                node_id="NODE-A", dedup_enabled=True, dedup_v_max=30.0,
                dedup_sigma_m=15.0, dedup_ttl=15.0)
    base.update(kw)
    return Settings(**base)


def rec(tid, source, dlat, dlon, ua, ts=T0, phase="CRUISE", battery=80):
    return {
        "id": tid, "source_node": source, "ts": ts,
        "lat": LAT + dlat, "lon": LON + dlon, "alt_msl": 120.0,
        "speed": 12.0, "heading": 45.0, "vertical_speed": 0.0,
        "battery_pct": battery, "link_quality": 4,
        "emergency": False, "rid_lost": False,
        "ua_id": ua, "reg_no": "REG-" + ua, "model": "EV-200", "phase": phase,
    }


def test_two_devices_dedup_and_fields_preserved():
    store = TrafficStore(make_settings())
    frame = [
        rec("7A21", "A-RID", 0.0000, 0.0000, ua="UA-1"),
        rec("7A22", "A-RID", 0.0020, 0.0020, ua="UA-2"),
        rec("7A23", "A-RID", 0.0040, 0.0040, ua="UA-3"),
        rec("7A24", "A-RID", 0.0060, 0.0000, ua="UA-4"),     # A 独有
        rec("7A25", "A-RID", 0.0080, 0.0000, ua="UA-5"),
        rec("8B01", "B-RID", 0.00005, 0.00005, ua="UA-1", battery=70),
        rec("8B02", "B-RID", 0.00205, 0.00205, ua="UA-2"),
        rec("8B03", "B-RID", 0.00405, 0.00405, ua="UA-3"),
        rec("8B04", "B-RID", 0.0070, 0.0020, ua="UA-6"),     # B 独有
        rec("8B05", "B-RID", 0.0090, 0.0020, ua="UA-7"),
    ]
    stats = store.ingest(frame, now=T0)
    out = store.snapshot()

    assert stats["input"] == 10
    assert stats["unique"] == 7, "应为 7 条唯一航迹，实际 %d" % stats["unique"]
    assert stats["merged"] == 3
    assert len(out) == 7

    merged = [r for r in out if r.get("merged")]
    assert len(merged) == 3
    for r in merged:
        assert set(r["sources"]) == {"A-RID", "B-RID"}
        assert set(r["source_ids"]) == {"A-RID", "B-RID"}
        # 业务字段必须保留（来自最新一条观测的原始 payload）
        assert r["phase"] == "CRUISE"
        assert r["battery_pct"] in (70, 80)
        assert r["id"] == r["ua_id"]           # 对外 id 用 ua_id，稳定且唯一
        assert r["callsign"] in ("7A21", "7A22", "7A23")   # 主源呼号，供界面展示

    single = [r for r in out if not r.get("merged")]
    assert len(single) == 4
    assert all(len(r["sources"]) == 1 for r in single)


def test_stats_endpoint_shape():
    store = TrafficStore(make_settings())
    store.ingest([rec("A1", "A-RID", 0, 0, ua="UA-1"),
                  rec("B1", "B-RID", 1e-5, 1e-5, ua="UA-1")], now=T0)
    st = store.stats()
    assert st["enabled"] is True
    assert st["unique_now"] == 1
    assert st["merged_now"] == 1
    assert {s["source"] for s in st["sources"]} == {"A-RID", "B-RID"}


def test_dedup_disabled_falls_back():
    store = TrafficStore(make_settings(dedup_enabled=False))
    stats = store.ingest([rec("A1", "A-RID", 0, 0, ua="UA-1"),
                          rec("B1", "B-RID", 1e-5, 1e-5, ua="UA-1")], now=T0)
    assert stats["enabled"] is False
    assert len(store.snapshot()) == 2, "关闭去重时应保留两条原始记录"


def test_stale_observation_ignored_in_legacy_mode():
    store = TrafficStore(make_settings(dedup_enabled=False))
    store.ingest([rec("A1", "A-RID", 0, 0, ua="UA-1", ts=T0 + 5)], now=T0 + 5)
    store.ingest([rec("A1", "A-RID", 0, 0, ua="UA-1", ts=T0)], now=T0 + 6)  # 旧数据
    assert store.snapshot()[0]["ts"] == T0 + 5


def test_iso_timestamp_accepted():
    store = TrafficStore(make_settings())
    r = rec("A1", "A-RID", 0, 0, ua="UA-1")
    r["ts"] = "2026-10-22T10:00:00+00:00"
    store.ingest([r], now=T0)
    assert len(store.snapshot()) == 1


if __name__ == "__main__":
    funcs = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    ok = True
    for name, fn in funcs:
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as exc:
            ok = False
            print("  FAIL  %s  %s" % (name, exc))
    print("全部通过 ✅" if ok else "存在失败项 ❌")
    sys.exit(0 if ok else 1)
