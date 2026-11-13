# -*- coding: utf-8 -*-
"""模拟 UOM / 地方低空平台接收端（用于本地联调，不依赖外部服务）。

运行：
    cd flight\\flycontrol\\low-altitude-demo\\backend
    python tools\\mock_uom_server.py --port 8099

接口：
    POST /uom/v1/messages   接收推送（校验 HMAC 签名，落盘到 uom_received.jsonl）
    GET  /uom/v1/messages   查看最近收到的消息（最多 20 条）
    GET  /health            健康检查

联调步骤：
    1) 启动本服务；
    2) 后端以真实发送模式启动：
       PUSH_MODE=http PUSH_ENDPOINT=http://127.0.0.1:8099/uom/v1/messages
    3) 打开门户「数据看板 → 数据推送」，或在命令行：
       Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/push/flush
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECENT = deque(maxlen=20)
LOCK = threading.Lock()
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uom_received.jsonl")


def verify(headers, body: bytes, app_key: str, app_secret: str) -> bool:
    ts = headers.get("X-Timestamp", "")
    nonce = headers.get("X-Nonce", "")
    got = headers.get("X-Signature", "")
    key = headers.get("X-App-Key", "")
    if not (ts and nonce and got):
        return False
    raw = "\n".join([key or app_key, ts, nonce, body.decode("utf-8")])
    want = hmac.new(app_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, got)


class Handler(BaseHTTPRequestHandler):
    app_key = "demo-app"
    app_secret = "demo-secret"

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 允许演示页面（5500）直接读取收到的报文
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json({"status": "ok", "service": "mock-uom", "port": self.server.server_port})
        if self.path.startswith("/uom/v1/messages"):
            with LOCK:
                return self._json({"count": len(RECENT), "messages": list(RECENT)})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/uom/v1/messages"):
            return self._json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        ok_sig = verify(self.headers, body, self.app_key, self.app_secret)
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return self._json({"code": 400, "msg": "invalid json"}, 400)

        record = {"received_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "signature_ok": ok_sig, "message": msg}
        with LOCK:
            RECENT.append(record)
            with open(OUT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print("  ← %-16s %s  sig=%s  tracks=%s" % (
            msg.get("msgType"), msg.get("msgId", "")[:10],
            "OK" if ok_sig else "FAIL",
            (msg.get("payload") or {}).get("count", "-")))

        if not ok_sig:
            return self._json({"code": 401, "msg": "signature mismatch"}, 401)
        return self._json({"code": 0, "msg": "ok", "msgId": msg.get("msgId")})

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--app-key", default="demo-app")
    ap.add_argument("--app-secret", default="demo-secret")
    args = ap.parse_args()

    Handler.app_key = args.app_key
    Handler.app_secret = args.app_secret

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Mock UOM 接收端已启动: http://%s:%d/uom/v1/messages" % (args.host, args.port))
    print("签名密钥: app_key=%s app_secret=%s（仅本地演示）" % (args.app_key, args.app_secret))
    print("落盘文件: %s\n" % OUT_FILE)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
