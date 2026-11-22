# -*- coding: utf-8 -*-
"""对外推送客户端（含签名）。

两种模式：
  - ``dry-run`` : 不真的发网络请求，直接算成功（默认，便于本地演示）；
  - ``http``    : 按 HMAC-SHA256 签名后 POST 到对端。

签名串（对端按同样规则校验）::

    string_to_sign = app_key + "\\n" + timestamp + "\\n" + nonce + "\\n" + body
    signature      = hex( HMAC-SHA256(app_secret, string_to_sign) )

请求头::

    X-App-Key / X-Timestamp / X-Nonce / X-Signature / Content-Type: application/json
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Optional

__all__ = ["PushClient", "SendResult", "sign"]


def sign(secret: str, app_key: str, timestamp: str, nonce: str, body: str) -> str:
    """HMAC-SHA256 签名（对端按同样规则校验）。"""
    raw = "\n".join([app_key, timestamp, nonce, body])
    return hmac.new(secret.encode("utf-8"), raw.encode("utf-8"),
                    hashlib.sha256).hexdigest()


@dataclass
class SendResult:
    ok: bool
    status: int = 0              # HTTP 状态码；dry-run 记 0
    latency_ms: float = 0.0
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {"ok": self.ok, "status": self.status,
                "latency_ms": round(self.latency_ms, 1), "error": self.error}


class PushClient:
    def __init__(self, mode: str = "dry-run", endpoint: str = "",
                 app_key: str = "", app_secret: str = "",
                 timeout: float = 5.0):
        self.mode = (mode or "dry-run").lower()
        self.endpoint = endpoint
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = float(timeout)

    def build_request(self, message: dict) -> tuple:
        """返回 (body_str, headers)。便于测试签名。"""
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex[:16]
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-App-Key": self.app_key,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
            "X-Signature": sign(self.app_secret, self.app_key, ts, nonce, body),
        }
        return body, headers

    def send(self, message: dict) -> SendResult:
        if self.mode == "dry-run":
            return SendResult(ok=True, status=0, latency_ms=0.0)
        if self.mode != "http":
            return SendResult(ok=False, error="Unsupported push mode: %s" % self.mode)
        if not self.endpoint:
            return SendResult(ok=False, error="HTTP push endpoint is missing")

        body, headers = self.build_request(message)
        req = urllib.request.Request(self.endpoint, data=body.encode("utf-8"),
                                     headers=headers, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read(2048)
                ms = (time.perf_counter() - t0) * 1000.0
                ok = 200 <= resp.status < 300
                return SendResult(ok=ok, status=resp.status, latency_ms=ms,
                                  error=None if ok else "HTTP %s" % resp.status)
        except urllib.error.HTTPError as exc:
            ms = (time.perf_counter() - t0) * 1000.0
            return SendResult(ok=False, status=exc.code, latency_ms=ms,
                              error="HTTP %s" % exc.code)
        except Exception as exc:  # noqa: BLE001  连接失败/超时等
            ms = (time.perf_counter() - t0) * 1000.0
            return SendResult(ok=False, status=0, latency_ms=ms, error=str(exc)[:200])
