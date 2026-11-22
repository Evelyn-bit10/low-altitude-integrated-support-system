# -*- coding: utf-8 -*-
"""
低空起降点一体化门户 · 地面站数据桥 (groundstation data bridge)
===============================================================
把地面站(groundstation)的机位/停靠调度/RID900 探测/Modbus 传感器数据
以 REST 形式提供给一体化门户。

数据来源有两层：
  1. 地面站真实上报（POST /api/ground/report）——优先使用，带 TTL
  2. 演示模拟（正弦波）——没有有效上报时回退，data_source=demo

依赖: 仅标准库。端口 8090。
接口:
  GET  /api/health         -> {"status":"ok","service":"ground-bridge","data_source":...}
  GET  /api/ground         -> {generated_at, data_source, stands, rid_targets, sensor, dispatch}
  POST /api/ground/report  -> 地面站上报（stands / rid_targets / sensor / dispatch）
"""
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8090
START = time.time()

# 上报有效期（秒）：超过后回退演示数据，避免门户拿旧数据当真
REPORT_TTL = float(os.getenv("GROUND_REPORT_TTL", "15"))

_REPORT = {"received_at": 0.0, "payload": None}
_REPORT_LOCK = threading.Lock()

STANDS = [
    {"id": "S-01", "name": "A01", "type": "indoor", "status": "occupied", "occupied_by": "UAV-CQ009", "charge_kw": 30, "max_size_m": 3.2, "priority": 1},
    {"id": "S-02", "name": "A02", "type": "indoor", "status": "reserved", "occupied_by": "UAV-CQ018", "charge_kw": 60, "max_size_m": 4.5, "priority": 2},
    {"id": "S-03", "name": "A03", "type": "indoor", "status": "free", "occupied_by": None, "charge_kw": 30, "max_size_m": 3.2, "priority": 3},
    {"id": "S-04", "name": "B01", "type": "outdoor", "status": "occupied", "occupied_by": "UAV-CQ031", "charge_kw": 22, "max_size_m": 5.5, "priority": 1},
    {"id": "S-05", "name": "B02", "type": "outdoor", "status": "free", "occupied_by": None, "charge_kw": 22, "max_size_m": 5.5, "priority": 4},
    {"id": "S-06", "name": "B03", "type": "outdoor", "status": "free", "occupied_by": None, "charge_kw": 11, "max_size_m": 4.0, "priority": 5},
]

RID_BASE = [
    {"id": "RID900-7A21", "vendor": "星网智控", "model": "RID900", "lat": 29.7231, "lon": 106.6465, "heading": 258, "speed": 6.4},
    {"id": "RID900-7A26", "vendor": "星网智控", "model": "RID900", "lat": 29.7064, "lon": 106.6234, "heading": 84, "speed": 13.2},
    {"id": "RID900-7A31", "vendor": "天域感知", "model": "RID900", "lat": 29.7305, "lon": 106.6172, "heading": 190, "speed": 4.6},
]


def _r(v, d=1):
    return round(float(v), d)


def _accept_report(payload):
    """校验并保存地面站上报。返回 (ok, detail)。"""
    if not isinstance(payload, dict):
        return False, "payload must be an object"
    for key, kind in (("stands", list), ("rid_targets", list), ("sensor", dict), ("dispatch", dict)):
        if key in payload and payload[key] is not None and not isinstance(payload[key], kind):
            return False, "%s must be %s" % (key, kind.__name__)
    with _REPORT_LOCK:
        _REPORT["received_at"] = time.time()
        _REPORT["payload"] = payload
    return True, "ok"


def _latest_report():
    """返回 (payload, age_sec)；没有或已过期返回 (None, None)。"""
    with _REPORT_LOCK:
        payload = _REPORT["payload"]
        age = (time.time() - _REPORT["received_at"]) if payload else None
    if not payload or age is None or age > REPORT_TTL:
        return None, None
    return payload, float(age)


def _build_from_report(payload, age):
    return {
        "airport_code": payload.get("airport_code") or "CQ-LX01",
        "data_source": "device",
        "report_age_sec": _r(age, 1),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stands": payload.get("stands") or [],
        "rid_targets": payload.get("rid_targets") or [],
        "sensor": payload.get("sensor") or {},
        "dispatch": payload.get("dispatch") or {},
    }


def build_ground_data():
    # 优先：地面站真实上报（未过期）
    payload, age = _latest_report()
    if payload is not None:
        return _build_from_report(payload, age)

    # 回退：演示模拟（正弦波）
    t = time.time() - START
    sensor = {
        "wind_speed": _r(5.8 + 1.6 * math.sin(t / 17) + 0.3 * math.sin(t / 5), 1),
        "wind_dir": _r((68 + 22 * math.sin(t / 31)) % 360, 0),
        "temperature": _r(27.4 + 1.2 * math.sin(t / 90), 1),
        "humidity": _r(66 + 5 * math.sin(t / 120), 0),
        "pressure": _r(1008.6 + 1.1 * math.sin(t / 200), 1),
        "light": int(4820 + 900 * math.sin(t / 60)),
        "rainfall": _r(max(0.0, 0.4 + 0.5 * math.sin(t / 45)), 1),
    }
    rid_targets = []
    for i, r in enumerate(RID_BASE):
        rid_targets.append({
            "id": r["id"], "vendor": r["vendor"], "model": r["model"],
            "lat": _r(r["lat"] + 0.0006 * math.sin(t / 23 + i), 5),
            "lon": _r(r["lon"] + 0.0007 * math.cos(t / 29 + i), 5),
            "alt_msl": _r(416 + i * 50 + 8 * math.sin(t / 13 + i), 0),
            "heading": int((r["heading"] + 12 * math.sin(t / 40 + i)) % 360),
            "speed": _r(max(0.0, r["speed"] + 1.5 * math.sin(t / 19 + i)), 1),
            "vertical_speed": _r(1.2 * math.sin(t / 21 + i), 1),
            "rssi": int(-58 + i * -6 + 4 * math.sin(t / 26 + i)),
            "snr": int(21 - i * 3 + 2 * math.sin(t / 33 + i)),
            "pilot_lat": _r(29.7178 - i * 0.004, 4),
            "pilot_lon": _r(106.6339 + i * 0.003, 4),
        })
    dispatch = {
        "waiting_count": int(2 + round(1.5 * (1 + math.sin(t / 37)))),
        "inbound": "UAV-CQ052 / 进入等待区" if (int(t / 20) % 3 == 2) else "UAV-CQ044 / 待确认",
        "outbound": "UAV-CQ018 / 准备离场",
        "deviation_alerts": int(1 + round(1 + math.sin(t / 53))),
    }
    return {
        "airport_code": "CQ-LX01",
        "data_source": "demo",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stands": STANDS,
        "rid_targets": rid_targets,
        "sensor": sensor,
        "dispatch": dispatch,
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/ground"):
            self._send_json(build_ground_data())
        elif self.path.startswith("/api/health"):
            payload, age = _latest_report()
            self._send_json({
                "status": "ok",
                "service": "ground-bridge",
                "port": PORT,
                "data_source": "device" if payload is not None else "demo",
                "report_age_sec": _r(age, 1) if age is not None else None,
                "report_ttl_sec": REPORT_TTL,
            })
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        if not self.path.startswith("/api/ground/report"):
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > 2_000_000:
            self._send_json({"ok": False, "error": "invalid body"}, status=400)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json({"ok": False, "error": "invalid json"}, status=400)
            return
        ok, detail = _accept_report(payload)
        self._send_json({"ok": ok, "detail": detail, "ttl_sec": REPORT_TTL},
                        200 if ok else 400)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="地面站数据桥 (groundstation data bridge)")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；手机真机测试用 0.0.0.0")
    ap.add_argument("--port", type=int, default=PORT, help="监听端口，默认 8090")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Ground data bridge online: http://%s:%d/api/ground" % (args.host, args.port))
    print("  POST /api/ground/report 接收地面站上报（TTL %.0fs）" % REPORT_TTL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
