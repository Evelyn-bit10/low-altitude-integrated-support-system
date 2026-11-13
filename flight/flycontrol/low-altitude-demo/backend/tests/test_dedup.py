# -*- coding: utf-8 -*-
"""去重引擎单元测试。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests/test_dedup.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.dedup import DedupEngine, Observation, distance_m  # noqa: E402

LAT, LON = 30.0, 120.0
T0 = 1000.0


M2D = 1.0 / 111320.0          # 1 米 ≈ 多少度纬度


def ob(src, tid, t, dlat, dlon, ua=None, reg=None, q=0.8, spd=12.0, hdg=45.0):
    return Observation(track_id=tid, source=src, ts=t,
                       lat=LAT + dlat, lon=LON + dlon,
                       alt_msl=120.0, speed=spd, heading=hdg,
                       ua_id=ua, reg_no=reg, quality=q)


def test_same_ua_id_merged():
    """同一条广播被两个设备收到 -> 一条航迹。"""
    eng = DedupEngine()
    r = eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-1"),
                    ob("B", "b1", T0, 0.00005, 0.00005, ua="UA-1", q=0.7)], now=T0)
    assert len(r.tracks) == 1
    assert r.tracks[0].ua_id == "UA-1"
    assert set(r.tracks[0].source_names) == {"A", "B"}


def test_different_ua_id_never_merged():
    """两架不同无人机靠得很近 -> 必须两条。"""
    eng = DedupEngine()
    r = eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-1"),
                    ob("B", "b1", T0, 0.00012, 0.00012, ua="UA-2")], now=T0)
    assert len(r.tracks) == 2
    assert {t.ua_id for t in r.tracks} == {"UA-1", "UA-2"}


def test_anonymous_geo_merge_and_inherit():
    """一方丢 ID，靠时空匹配合并，并继承对方 ua_id。"""
    eng = DedupEngine()
    r = eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-9"),
                    ob("B", "b1", T0, 0.00008, 0.00006, ua=None)], now=T0)
    assert len(r.tracks) == 1
    t = r.tracks[0]
    assert t.ua_id == "UA-9"
    assert len(t.sources) == 2
    assert eng.by_ua["UA-9"] == t.global_id


def test_duplicate_message_idempotent():
    """同一条报文重复上报 -> 只算一次。"""
    eng = DedupEngine()
    o = ob("A", "a1", T0, 0, 0, ua="UA-1")
    r = eng.ingest([o, o], now=T0)
    assert len(r.tracks) == 1
    assert r.stats["duplicate"] == 1


def test_ttl_keeps_track_across_gap():
    """消失 8 秒（< TTL 15s）后重现 -> 仍是同一条。"""
    eng = DedupEngine(ttl=15.0)
    eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-1")], now=T0)
    gid = eng.by_ua["UA-1"]
    for k in range(1, 9):
        eng.ingest([ob("A", "other", T0 + k, 0.01, 0.01, ua="UA-OTHER")], now=T0 + k)
    r = eng.ingest([ob("A", "a1", T0 + 9, 0.0002, 0, ua="UA-1")], now=T0 + 9)
    assert len([t for t in r.tracks if t.ua_id == "UA-1"]) == 1
    assert eng.by_ua["UA-1"] == gid


def test_expired_after_ttl():
    """超过 TTL 未更新 -> 航迹被删除。"""
    eng = DedupEngine(ttl=5.0)
    eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-1")], now=T0)
    for k in range(1, 8):
        eng.ingest([ob("A", "other", T0 + k, 0.01, 0.01, ua="UA-X%d" % k)], now=T0 + k)
    assert "UA-1" not in eng.by_ua


def test_multi_frame_stable():
    """连续 10 帧、目标缓慢移动 -> 航迹数稳定，不增生。"""
    eng = DedupEngine()
    uas = ["UA-1", "UA-2", "UA-3"]
    for k in range(10):
        t = T0 + k
        frame = []
        for i, ua in enumerate(uas):
            frame.append(ob("A", "a%d" % i, t, 0.000108 * k + 0.000216 * i, 0.000108 * k, ua=ua))
            frame.append(ob("B", "b%d" % i, t, 0.000108 * k + 0.000216 * i + 1e-5,
                            0.000108 * k + 1e-5, ua=None, q=0.6))
        r = eng.ingest(frame, now=t)
        assert len(r.tracks) == 3, "第 %d 帧航迹数变成 %d" % (k, len(r.tracks))
    assert all(len(t.sources) == 2 for t in r.tracks)


def test_many_targets_no_cross_merge():
    """20 架密集目标：只合并同一 ua_id，不误并。"""
    eng = DedupEngine()
    frame = []
    for i in range(20):
        ua = "UA-%03d" % i
        frame.append(ob("A", "a%d" % i, T0, 0.0004 * i, 0.0003 * i, ua=ua))
        frame.append(ob("B", "b%d" % i, T0, 0.0004 * i + 2e-5, 0.0003 * i, ua=ua))
    r = eng.ingest(frame, now=T0)
    assert len(r.tracks) == 20
    assert all(len(t.sources) == 2 for t in r.tracks)


def test_gate_rejects_far_target():
    """超出门限的同一 ua_id 仍按 ID 合并（ID 优先于距离）。"""
    eng = DedupEngine()
    eng.ingest([ob("A", "a1", T0, 0, 0, ua="UA-1")], now=T0)
    r = eng.ingest([ob("B", "b1", T0 + 5, 0.01, 0.01, ua="UA-1")], now=T0 + 5)
    assert len(r.tracks) == 1


def test_anonymous_cannot_steal_identity():
    """已失联的有 ID 航迹，不能被另一设备的一架无 ID 飞机「继承身份」。"""
    eng = DedupEngine(ttl=30.0)
    eng.ingest([ob("A", "k1", T0, 0, 0, ua="UA-1")], now=T0)
    # UA-1 失联 3 帧（用别的目标推进时间）
    for k in (1, 2, 3):
        eng.ingest([ob("C", "c%d" % k, T0 + k, 0.01, 0.01, ua="UA-OTHER-%d" % k)],
                   now=T0 + k)
    # 另一台设备的无 ID 目标出现在 30 m 外
    eng.ingest([ob("B", "u1", T0 + 4, 30 * M2D, 0)], now=T0 + 4)

    ua1 = eng.tracks[eng.by_ua["UA-1"]]
    assert "B" not in ua1.sources, "UA-1 的航迹被无 ID 目标污染了"
    assert len(ua1.sources) == 1
    print("    （UA-1 航迹来源：%s）" % ua1.source_names)


def test_heading_glitch_no_ghost():
    """单帧航向报文出错，不应在旧航迹旁新建「幽灵」。"""
    eng = DedupEngine()
    for k in range(3):
        eng.ingest([ob("R", "t1", T0 + k, 10 * k * M2D, 0, hdg=90.0),
                    ob("R", "t2", T0 + k, (60 + 10 * k) * M2D, 0, hdg=90.0)],
                   now=T0 + k)
    r = eng.ingest([ob("R", "t1", T0 + 3, 30 * M2D, 0, hdg=300.0),
                    ob("R", "t2", T0 + 3, 90 * M2D, 0, hdg=90.0)], now=T0 + 3)
    assert len(r.tracks) == 2, "航向报错后多出幽灵航迹：%d 条" % len(r.tracks)
    assert eng.tracks and all(len(t.sources) <= 1 for t in r.tracks)


def test_lost_track_not_taken_over_by_other_source():
    """失联航迹不会被「别的设备看到的另一架」接管（安全优先）。"""
    eng = DedupEngine(ttl=30.0)
    eng.ingest([ob("A", "k1", T0, 0, 0, ua="UA-1")], now=T0)
    for k in (1, 2, 3):
        eng.ingest([ob("C", "c%d" % k, T0 + k, 0.02, 0.02, ua="UA-X-%d" % k)],
                   now=T0 + k)
    r = eng.ingest([ob("B", "u1", T0 + 4, 40 * M2D, 0)], now=T0 + 4)
    assert len([t for t in r.tracks if t.ua_id == "UA-1"]) == 1
    assert all("B" not in t.sources for t in r.tracks if t.ua_id == "UA-1")


def test_tentative_not_visible():
    """无 ID 的新目标第一帧不对外输出（避免抖动导致界面多一条）。"""
    eng = DedupEngine()
    r1 = eng.ingest([ob("R", "x1", T0, 0, 0)], now=T0)
    assert len(r1.tracks) == 0, "未确认航迹不应输出"
    assert r1.stats.get("tentative") == 1
    r2 = eng.ingest([ob("R", "x1", T0 + 1, 10 * M2D, 0)], now=T0 + 1)
    assert len(r2.tracks) == 1, "连续两帧后应确认并输出"


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
