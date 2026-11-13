# -*- coding: utf-8 -*-
"""影子模式（RL 策略跟跑）测试。"""
from __future__ import annotations

import json
import os

import pytest

from app.routers.traffic import TrafficStore
from app.services import shadow as sh


def _obs(lat, lon, src, rid, alt=100.0, spd=10.0, hdg=90.0, ua=None, ts=None):
    return {"id": rid, "lat": lat, "lon": lon, "alt_msl": alt, "speed": spd,
            "heading": hdg, "source_node": src, "ua_id": ua, "ts": ts or 1761000000.0}


@pytest.fixture()
def logfile(tmp_path, monkeypatch):
    p = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("DEDUP_SHADOW", "1")
    monkeypatch.setenv("DEDUP_SHADOW_LOG", str(p))
    return p


def test_features_match_training_order():
    """18 维特征的顺序必须与训练时一致，否则策略输入就是错的。"""
    assert len(sh.FEATURE_NAMES) == 19
    assert sh.FEATURE_NAMES[-3:] == ["最近邻航迹距离/100", "航迹总数/100", "门限膨胀比"]


def test_default_off(monkeypatch):
    monkeypatch.delenv("DEDUP_SHADOW", raising=False)
    s = sh.build_from_env()
    assert s.enabled is False
    assert "DEDUP_SHADOW" in s.reason


def test_shadow_runs_and_logs(logfile):
    store = TrafficStore(settings=None)
    assert store.shadow is not None and store.shadow.enabled

    t0 = 1761000000.0
    # 同一架飞机，两个设备各报一次（相距 12 m，应被规则合并；策略应当也同意）
    # 连续 3 帧（航迹需要几帧才能从 TENTATIVE 转 CONFIRMED）
    for k in range(3):
        store.ingest([
            _obs(30.5000 + k * 0.0001, 114.4000, "A-RID", "A1", ts=t0 + k),
            _obs(30.5001 + k * 0.0001, 114.4000, "B-RID", "B1", ts=t0 + k + 0.5),
        ], now=t0 + k + 0.5)

    st = store.shadow.stats()
    assert st["enabled"] is True
    # 第一帧还没有候选航迹，做不了比对；从第 2 帧起才开始有边
    assert st["frames"] == 2
    assert st["observations"] == 4
    assert st["agree"] + st["policy_extra"] + st["policy_missed"] + st["both_new"]         == st["observations"]
    assert logfile.exists()
    rows = [json.loads(x) for x in logfile.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == st["observations"]
    assert {"frame", "src", "rule_gid", "policy_gid", "p_max", "agree"} <= set(rows[0])


def test_shadow_never_breaks_ingest(logfile, monkeypatch):
    """策略文件坏掉时，影子必须静默降级，主流程照常出结果。"""
    store = TrafficStore(settings=None)
    store.shadow.policy = None
    store.shadow.enabled = True          # 人为制造损坏状态
    stats = store.ingest([_obs(30.5, 114.4, "A-RID", "A1")])
    assert stats["created"] >= 1          # 主流程无影响


def test_hard_mask_blocks_conflicting_ua():
    """ua_id 冲突的边必须被硬屏蔽（安全规则）。"""
    o = type("O", (), {"lat": 30.5, "lon": 114.4, "alt_msl": 100, "speed": 10,
                       "heading": 90, "ua_id": "UA-X", "reg_no": None,
                       "quality": 0.6, "sigma": 10.0, "source": "A", "track_id": "A1"})()
    snap = [{"gid": "UA-0001", "x": 0.0, "y": 0.0, "z": 100, "heading": 90,
             "speed": 10, "ua_id": "UA-Y", "reg_no": None, "last_t": 0.0, "seen": 3}]
    origin = (30.5, 114.4)
    feats, meta, hard = sh.build_edges([o], snap, 1.0, origin)
    assert len(feats) == 1 and hard == [1.0]
    assert sh.decode([0.99], 0.3, meta, hard, ["A"]) == {}


# ---------------------------------------------------------------- 分配 / 回并

def test_hungarian_matches_bruteforce():
    """匈牙利实现必须和暴力最优一致。"""
    import itertools
    import random
    from app.services.assignment import max_weight_matching
    rng = random.Random(7)
    for _ in range(60):
        n, m = rng.randint(1, 4), rng.randint(n if False else 1, 4)
        W = [[round(rng.random(), 2) for _ in range(m)] for _ in range(n)]
        got = max_weight_matching(W, 0.0)
        s = sum(W[i][got[i]] if got[i] is not None else 0 for i in range(n))
        if n <= m:
            best = max(sum(W[i][c[i]] for i in range(n))
                       for c in itertools.permutations(range(m), n))
        else:
            best = max(sum(W[c[j]][j] for j in range(m))
                       for c in itertools.permutations(range(n), m))
        assert abs(s - best) < 1e-6


def _mk_obs(lat, lon, src, tid, ua=None, ts=0.0):
    from app.services.dedup import Observation
    return Observation(track_id=tid, source=src, ts=ts, lat=lat, lon=lon,
                       alt_msl=100.0, speed=10.0, heading=90.0,
                       ua_id=ua, reg_no=None, sigma=12.0)


def test_post_merge_joins_split_tracks():
    """同一架被拆成两条航迹时，事后回并应该合回一条。"""
    from app.services.dedup import DedupEngine
    eng = DedupEngine(node_id="T", gate_k=3.44, post_merge=True, ttl=15.0)
    # 连续几帧正常
    for k in range(4):
        eng.ingest([_mk_obs(30.0, 120.0 + k * 1e-5, "A-RID", "A1", ts=k),
                    _mk_obs(30.0001, 120.0 + k * 1e-5, "B-RID", "B1", ts=k)], now=k)
    assert len(eng.tracks) == 1
    # 制造一条"错开"的碎片：用一条几乎重合、只有另一来源的航迹
    track = list(eng.tracks.values())[0]
    t2 = eng._create(_mk_obs(track.lat, track.lon, "C-RID", "C1", ts=4.0), 4.0)
    t2.hits = 5
    before = len(eng.tracks)
    res = eng.ingest([], now=4.5)
    assert res.stats.get("post_merged", 0) >= 1
    assert len(eng.tracks) < before


# ---------------------------------------------------------------- 卡尔曼滤波

def test_kalman_converges_to_constant_velocity():
    """匀速目标：位置/速度应收敛到真值附近。"""
    from app.services.kalman import KalmanCV
    kf = KalmanCV(0.0, 0.0, sigma_pos=20.0, sigma_vel=15.0, sigma_a=1.5)
    x, y, vx, vy = 0.0, 0.0, 20.0, -8.0
    for _ in range(40):
        kf.predict(1.0)
        x += vx; y += vy
        kf.update(x + 3.0, y - 2.0, 12.0)      # 带常值偏差的观测
    assert abs(kf.vx - vx) < 2.0
    assert abs(kf.vy - vy) < 2.0
    assert abs(kf.px - x) < 25.0


def test_kalman_covariance_stays_positive_and_symmetric():
    """长时间不观测：P 应该涨但有界；更新后应该缩小。"""
    from app.services.kalman import KalmanCV
    kf = KalmanCV(0.0, 0.0)
    for _ in range(200):
        kf.predict(1.0)
    assert kf.P[0][0] > 0 and kf.P[3][3] > 0
    for i in range(4):
        for j in range(4):
            assert abs(kf.P[i][j] - kf.P[j][i]) < 1e-9
    big = kf.P[0][0]
    for _ in range(5):
        kf.update(0.0, 0.0, 10.0)
    assert kf.P[0][0] < big


def test_kalman_gate_grows_with_dt():
    """越久没观测，门限应该越大（不确定度随时间增长）。"""
    from app.services.kalman import KalmanCV
    kf = KalmanCV(0.0, 0.0, sigma_pos=8.0, sigma_vel=10.0, sigma_a=2.0)
    kf.predict(1.0)
    _, s1 = kf.innovation(0.0, 0.0, 10.0)
    kf.predict(5.0)
    _, s2 = kf.innovation(kf.px, kf.py, 10.0)      # 站在预测点上量，只反映不确定度
    assert s2 > s1


def test_kalman_gate_is_directional():
    """协方差各向异性时，门限沿那个方向更宽（椭圆）。"""
    from app.services.kalman import KalmanCV
    kf = KalmanCV(0.0, 0.0, sigma_pos=5.0, sigma_vel=0.0, sigma_a=0.0)
    kf.P[0][0] = 25.0           # x 方向很确定
    kf.P[1][1] = 400.0          # y 方向不确定 -> 该方向门限应更宽
    _, s_x = kf.innovation(50.0, 0.0, 5.0)
    _, s_y = kf.innovation(0.0, 50.0, 5.0)
    assert s_y > s_x * 2.0


def test_engine_uses_kalman_by_default():
    from app.services.dedup import DedupEngine
    eng = DedupEngine(node_id="T")
    assert eng.use_kalman is True
    eng.ingest([_mk_obs(30.0, 120.0, "A-RID", "A1", ts=0.0)], now=0.0)
    track = list(eng.tracks.values())[0]
    assert track.kf is not None


def test_gate_is_capped_by_classic_formula():
    """长时间无观测时滤波协方差会膨胀，门限必须被经典式封顶。"""
    import math
    from app.services.dedup import DedupEngine
    eng = DedupEngine(node_id="T")
    eng.ingest([_mk_obs(30.0, 120.0, "A-RID", "A1", ts=0.0)], now=0.0)
    t = list(eng.tracks.values())[0]
    o = _mk_obs(30.0, 120.0, "A-RID", "A1", ts=600.0)
    g = eng._gate(o, t, 600.0)
    s_obs = o.sigma or 12.0
    classic = eng.gate_k * math.sqrt(s_obs ** 2 + eng._track_sigma(t) ** 2
                                     + eng._motion_sigma(t, 600.0) ** 2)
    assert g <= classic + 1e-6
    assert g >= 1.0
