# -*- coding: utf-8 -*-
"""对外推送测试：报文适配 / 签名 / 发件箱 / 推送服务。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    pytest tests/test_push.py -q
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings                                  # noqa: E402
from app.integrations import uom_adapter as Adapter              # noqa: E402
from app.integrations.outbox import Outbox                       # noqa: E402
from app.integrations.uom_client import PushClient, sign         # noqa: E402
from app.services.push_service import PushService                # noqa: E402

T0 = 1000.0


# ------------------------------------------------------------------ 适配层
def test_envelope_and_msg_id_are_deterministic():
    m1 = Adapter.message_for("METEO", "NODE-A", {"a": 1}, ts=T0)
    m2 = Adapter.message_for("METEO", "NODE-A", {"a": 1}, ts=T0)
    assert m1["msgId"] == m2["msgId"], "同内容同时刻应生成相同 msgId（幂等）"
    assert m1["msgType"] == "METEO"
    assert m1["source"]["nodeId"] == "NODE-A"
    assert m1["version"] == Adapter.SPEC_VERSION


def test_msg_id_changes_with_content():
    a = Adapter.message_for("METEO", "NODE-A", {"a": 1}, ts=T0)
    b = Adapter.message_for("METEO", "NODE-A", {"a": 2}, ts=T0)
    assert a["msgId"] != b["msgId"]


def test_track_payload_mapping():
    tracks = [{"ua_id": "UA-1", "reg_no": "REG-1", "lat": 30.0, "lon": 120.0,
               "alt_msl": 120.0, "speed": 12.0, "heading": 45.0,
               "phase": "CRUISE", "ts": "2026-10-22T10:00:00Z",
               "sources": ["A-RID", "B-RID"], "confidence": 0.9}]
    p = Adapter.track_payload(tracks)
    assert p["count"] == 1
    t = p["tracks"][0]
    assert t["uasId"] == "UA-1"
    assert t["groundSpeed"] == 12.0
    assert t["flightPhase"] == "CRUISE"
    assert t["sources"] == ["A-RID", "B-RID"]


def test_program_payload_keeps_direction():
    prog = {"type": "arrival", "version": "v3", "source": "plan",
            "direction": "NE", "std_name": "ARR-NE",
            "waypoints": [{"lat": 30.1, "lon": 120.1, "alt_msl": 250, "speed": 25}],
            "miss_approach": []}
    p = Adapter.program_payload(prog, "LAC-DEMO")
    assert p["direction"] == "NE" and p["stdName"] == "ARR-NE"
    assert p["waypoints"][0]["altMsl"] == 250


# ------------------------------------------------------------------ 签名
def test_signature_is_stable():
    s1 = sign("secret", "app", "1700000000", "abc", '{"a":1}')
    s2 = sign("secret", "app", "1700000000", "abc", '{"a":1}')
    assert s1 == s2 and len(s1) == 64
    assert sign("other", "app", "1700000000", "abc", '{"a":1}') != s1


def test_client_build_request_headers():
    c = PushClient(mode="http", endpoint="http://x", app_key="k", app_secret="s")
    body, headers = c.build_request({"msgId": "m1"})
    assert headers["X-App-Key"] == "k"
    assert headers["X-Signature"] == sign("s", "k", headers["X-Timestamp"],
                                          headers["X-Nonce"], body)


def test_dry_run_client_always_ok():
    res = PushClient(mode="dry-run").send({"msgId": "x"})
    assert res.ok and res.status == 0


def test_invalid_push_configuration_does_not_report_success():
    for client in (PushClient(mode="http"), PushClient(mode="invalid")):
        result = client.send({"msgId": "x"})
        assert not result.ok
        assert result.error


# ------------------------------------------------------------------ 发件箱
def _outbox():
    return Outbox(":memory:", max_attempts=3)


def test_outbox_dedup_and_stats():
    ob = _outbox()
    msg = Adapter.message_for("METEO", "N", {"v": 1}, ts=T0)
    assert ob.enqueue(msg, "meteo", now=T0) is True
    assert ob.enqueue(msg, "meteo", now=T0) is False, "重复 msgId 不应重复入队"
    st = ob.stats(now=T0)
    assert st["pending"] == 1 and st["sent"] == 0


def test_outbox_retry_backoff_and_dead():
    ob = _outbox()
    msg = Adapter.message_for("METEO", "N", {"v": 2}, ts=T0)
    ob.enqueue(msg, "meteo", now=T0)
    assert len(ob.due(now=T0 + 1)) == 1

    assert ob.mark_failed(msg["msgId"], "boom", now=T0) == "pending"
    assert ob.due(now=T0 + 1) == [], "退避期内不应重发"
    assert len(ob.due(now=T0 + 10)) == 1

    ob.mark_failed(msg["msgId"], "boom", now=T0 + 10)
    assert ob.mark_failed(msg["msgId"], "boom", now=T0 + 20) == "dead"
    assert ob.stats(now=T0 + 21)["dead"] == 1
    assert ob.requeue_dead() == 1
    assert len(ob.due(now=T0 + 22, force=True)) == 1


def test_outbox_force_due_ignores_backoff():
    ob = _outbox()
    msg = Adapter.message_for("METEO", "N", {"v": 3}, ts=T0)
    ob.enqueue(msg, "meteo", now=T0)
    ob.mark_failed(msg["msgId"], "err", now=T0)
    assert ob.due(now=T0 + 0.1) == []
    assert len(ob.due(now=T0 + 0.1, force=True)) == 1


# ------------------------------------------------------------------ 推送服务
class FakeStore:
    class _AP:
        code = "LAC-DEMO"
    airport = _AP()

    def __init__(self):
        self.current_program = None
        self.meteo = None

    @staticmethod
    def _to_latlon(x, y, z):
        return 30.0 + y / 111320.0, 120.0 + x / 111320.0, 60.0 + z


class FakeTraffic:
    def __init__(self):
        self.tracks = []

    def snapshot(self):
        return list(self.tracks)


class OkClient:
    def __init__(self):
        self.mode = "fake"
        self.endpoint = "memory"
        self.sent = []

    def send(self, msg):
        from app.integrations.uom_client import SendResult
        self.sent.append(msg)
        return SendResult(ok=True, status=200, latency_ms=3.0)


class BadClient(OkClient):
    def send(self, msg):
        from app.integrations.uom_client import SendResult
        return SendResult(ok=False, status=500, latency_ms=2.0, error="HTTP 500")


def _svc(client=None, **kw):
    s = Settings(database_url="sqlite://", dispatch_interval=2.0, auth_enabled=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return PushService(FakeStore(), FakeTraffic(), s,
                       client=client or OkClient(), outbox=_outbox())


def test_service_collects_and_sends():
    svc = _svc()
    svc.traffic.tracks = [{"ua_id": "UA-1", "lat": 30.0, "lon": 120.0,
                           "alt_msl": 100, "speed": 10, "heading": 90,
                           "phase": "CRUISE", "ts": "t"}]
    added = svc.collect(now=T0)
    assert added >= 1
    res = asyncio.run(svc.drain(force=True))
    assert res["sent"] >= 1 and res["failed"] == 0
    st = svc.status()
    assert st["queue"]["sent"] >= 1
    assert st["success_rate"] == 1.0


def test_service_retries_on_failure():
    svc = _svc(client=BadClient())
    svc.traffic.tracks = [{"ua_id": "UA-1", "lat": 30.0, "lon": 120.0,
                           "alt_msl": 100, "speed": 10, "heading": 90,
                           "phase": "CRUISE", "ts": "t"}]
    svc.collect(now=T0)
    res = asyncio.run(svc.drain(force=True))
    assert res["failed"] >= 1
    st = svc.status()
    assert st["queue"]["pending"] >= 1
    assert st["last_error"] == "HTTP 500"


def test_service_dedups_identical_messages():
    svc = _svc()
    svc.traffic.tracks = [{"ua_id": "UA-1", "lat": 30.0, "lon": 120.0,
                           "alt_msl": 100, "speed": 10, "heading": 90,
                           "phase": "CRUISE", "ts": "t"}]
    svc.collect(now=T0)
    before = svc.counters["enqueued"]
    # 同一时刻重复采集：content 相同 -> msgId 相同 -> 去重
    svc._last_track_at = 0.0
    svc.collect(now=T0)
    assert svc.counters["enqueued"] == before


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
