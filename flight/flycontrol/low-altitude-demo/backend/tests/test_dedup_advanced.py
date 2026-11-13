# -*- coding: utf-8 -*-
"""去重引擎的进阶行为测试：时钟对齐、σ 门限、拆分阈值、网格索引、告警推送。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests\\test_dedup_advanced.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings                                   # noqa: E402
from app.services.dedup import DedupEngine, Observation            # noqa: E402
from app.services.push_service import PushService                  # noqa: E402

LAT, LON = 30.0, 120.0
M2D = 1.0 / 111320.0
T0 = 1000.0


def ob(src, tid, t, dlat=0.0, dlon=0.0, ua=None, sigma=None, q=0.6):
    return Observation(track_id=tid, source=src, ts=t,
                       lat=LAT + dlat, lon=LON + dlon, alt_msl=120.0,
                       speed=10.0, heading=45.0, ua_id=ua, quality=q, sigma=sigma)


# ------------------------------------------------------------------ 时钟
def test_clock_skew_is_estimated_and_corrected():
    """B 设备时钟慢 5 秒：引擎应估出 +5 s 偏移，且两个源仍能合并。"""
    eng = DedupEngine(node_id="T", sigma_m=15.0)
    for k in range(8):
        t = T0 + k
        eng.ingest([
            ob("A-RID", "A1", t, 0, 0, ua="UA-1", sigma=10),
            ob("B-RID", "B1", t - 5.0, 0.00005, 0.00005, ua="UA-1", sigma=30),  # 慢 5 s
        ], now=t)
    assert abs(eng.clock_offset["B-RID"] - 5.0) < 0.3, eng.clock_offset
    assert abs(eng.clock_offset["A-RID"]) < 0.3
    assert len(eng.tracks) == 1, "时钟偏差被校正后应只有一条航迹"
    assert len(eng.tracks[eng.by_ua["UA-1"]].sources) == 2


def test_clock_offset_ignores_absurd_timestamp():
    """时间戳离谱（>120 s）时不参与校正，也不污染偏移估计。"""
    eng = DedupEngine()
    eng.ingest([ob("A-RID", "A1", T0, ua="UA-1")], now=T0)
    eng.ingest([ob("A-RID", "A2", T0 - 9999, ua="UA-2")], now=T0)
    assert eng.clock_offset.get("A-RID", 0.0) == 0.0


# ------------------------------------------------------------------ σ 门限
def test_gate_scales_with_source_sigma():
    """同样的 60 m 偏差：σ 小 → 不合并；σ 大 → 合并。"""
    def merge_with(sigma):
        eng = DedupEngine(node_id="T")
        eng.ingest([ob("A-RID", "A1", T0, 0, 0, sigma=sigma)], now=T0)
        eng.ingest([ob("B-RID", "B1", T0, 60 * M2D, 0, sigma=sigma)], now=T0)
        return len(eng.tracks)

    assert merge_with(10.0) == 2, "σ=10 时 60 m 超出 3.44σ，不应合并"
    assert merge_with(30.0) == 1, "σ=30 时 60 m 在门限内，应合并"


def test_sigma_floor_protects_against_underestimate():
    """σ 被填得过小（如 1 m）时，下限保护会阻止门限塌缩。"""
    eng = DedupEngine(node_id="T", sigma_floor=8.0, source_sigmas={"A-RID": 1.0})
    assert eng.sigma_of("A-RID") == 8.0


# ------------------------------------------------------------------ 拆分
def test_split_not_triggered_by_noise_difference():
    """两个源噪声差 4 倍时，70 m 的正常偏差不应把一条航迹拆成两条。"""
    eng = DedupEngine(node_id="T", source_sigmas={"A-RID": 10.0, "B-RID": 45.0})
    for k in range(6):
        t = T0 + k
        eng.ingest([
            ob("A-RID", "A1", t, 0, 0, ua="UA-1", sigma=10),
            ob("B-RID", "B1", t, 70 * M2D, 0, ua="UA-1", sigma=45),
        ], now=t)
    assert len(eng.tracks) == 1, "噪声差异导致的偏差不应触发拆分"


# ------------------------------------------------------------------ 网格
def test_grid_index_matches_full_scan():
    """启用网格索引（>200 目标）与全量扫描的结果应一致。"""
    def run(threshold):
        eng = DedupEngine(node_id="T", grid_threshold=threshold)
        obs = [ob("A-RID", "A%d" % i, T0, dlat=(i % 20) * 3 * M2D,
                  dlon=(i // 20) * 3 * M2D, ua="UA-%03d" % i) for i in range(300)]
        eng.ingest(obs, now=T0)
        # 第二帧：全部平移 5 m，仍应各自对应
        obs2 = [ob("A-RID", "A%d" % i, T0 + 1, dlat=(i % 20) * 3 * M2D + 5 * M2D,
                   dlon=(i // 20) * 3 * M2D, ua="UA-%03d" % i) for i in range(300)]
        eng.ingest(obs2, now=T0 + 1)
        return len(eng.tracks)

    assert run(10 ** 9) == run(200) == 300


# ------------------------------------------------------------------ 告警推送
class _Store:
    class _AP:
        code = "LAC-DEMO"
    airport = _AP()

    def __init__(self, alarm=None):
        self.current_program = None
        self.meteo = None
        self.last_alarm = alarm

    @staticmethod
    def _to_latlon(x, y, z):
        return LAT + y / 111320.0, LON + x / 111320.0, 60.0 + z


class _Traffic:
    def snapshot(self):
        return []


class _Client:
    mode = "fake"
    endpoint = "memory"

    def __init__(self):
        self.sent = []

    def send(self, msg):
        from app.integrations.uom_client import SendResult
        self.sent.append(msg)
        return SendResult(ok=True, status=200, latency_ms=1.0)


def test_alert_message_pushed_once():
    """last_alarm 变化时推一条 ALERT，同样的告警不重复推。"""
    from app.integrations.outbox import Outbox
    store = _Store(alarm="禁飞级风险(禁飞级), 无可用程序")
    client = _Client()
    svc = PushService(store, _Traffic(),
                      Settings(database_url="sqlite://", dispatch_interval=2.0,
                               auth_enabled=False),
                      client=client, outbox=Outbox(":memory:"))
    svc.collect(now=T0)
    svc.collect(now=T0 + 1)
    alerts = [m for m in client.sent if m["msgType"] == "ALERT"] if client.sent else []
    # 只入队不发送，检查发件箱里的 ALERT 条数
    rows = svc.outbox.due(now=T0 + 10, limit=50, force=True)
    alerts = [r for r in rows if r["payload"]["msgType"] == "ALERT"]
    assert len(alerts) == 1, "同一告警只应入队一次"
    assert alerts[0]["payload"]["payload"]["level"] == "WARNING"


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


# ------------------------------------------------------------------ σ 自标定
def test_sigma_autocalibration_recovers_scale():
    """配置值故意填错（20/20），真实噪声 10/30：在线标定应收敛到正确尺度。"""
    import random
    rng = random.Random(3)
    eng = DedupEngine(node_id="T", source_sigmas={"A-RID": 20.0, "B-RID": 20.0},
                      sigma_autocalib=True, sigma_calib_samples=100)
    x = 0.0
    for k in range(400):
        x += 5.0                      # 匀速东移
        t = T0 + k
        # 位置按"米 -> 经纬度"转换，与引擎 distance_m 的换算保持一致
        ax, ay = x + rng.gauss(0, 10), rng.gauss(0, 10)
        bx, by = x + rng.gauss(0, 30), rng.gauss(0, 30)
        eng.ingest([
            ob("A-RID", "A1", t, dlat=ay * M2D, dlon=ax * M2D / 0.866,
               ua="UA-1", sigma=None),
            ob("B-RID", "B1", t, dlat=by * M2D, dlon=bx * M2D / 0.866,
               ua="UA-1", sigma=None),
        ], now=t)
    # 期望尺度 = sqrt((10²+30²)/(20²+20²)) = sqrt(1.25) ≈ 1.118
    assert abs(eng.sigma_scale - 1.118) < 0.2, eng.sigma_scale
    assert eng.sigma_of("A-RID") > 20.0, "配置偏小时应被自动放大"


def test_sigma_autocalibration_can_be_disabled():
    eng = DedupEngine(node_id="T", source_sigmas={"A-RID": 20.0, "B-RID": 20.0},
                      sigma_autocalib=False)
    for k in range(50):
        eng.ingest([ob("A-RID", "A1", T0 + k, ua="UA-1"),
                    ob("B-RID", "B1", T0 + k, dlon=30 * M2D, ua="UA-1")], now=T0 + k)
    assert eng.sigma_scale == 1.0
