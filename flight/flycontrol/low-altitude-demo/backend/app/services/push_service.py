# -*- coding: utf-8 -*-
"""对外推送服务：采集 → 组装报文 → 入发件箱 → 发送（带重试）。

推送内容（都可单独关闭 / 调频）：
  1. 实时态势 SURVEILLANCE  —— 每 `push_track_interval` 秒一批（已去重）
  2. 飞行程序 FLIGHT_PROGRAM —— 版本变化时推一次
  3. 气象     METEO          —— 气象变化时推一次

设计要点：
  - **先入箱再发送**：网络故障不丢数据，重启可续传；
  - **幂等**：msgId 由内容哈希生成，重复采集不会重复推送；
  - **重试**：指数退避（2s → 4s → … → 60s），超过 max_attempts 记 dead；
  - **不阻塞主循环**：发送在独立 asyncio 任务里，HTTP 调用丢到线程池。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ..integrations import uom_adapter as adapter
from ..integrations.outbox import Outbox
from ..integrations.uom_client import PushClient

log = logging.getLogger("lowalt.push")


class PushService:
    def __init__(self, store, traffic, settings,
                 client: Optional[PushClient] = None,
                 outbox: Optional[Outbox] = None):
        self.store = store
        self.traffic = traffic
        self.settings = settings
        self.enabled = bool(getattr(settings, "push_enabled", True))
        self.node_id = str(getattr(settings, "node_id", "NODE-A"))

        self.client = client or PushClient(
            mode=getattr(settings, "push_mode", "dry-run"),
            endpoint=getattr(settings, "push_endpoint", ""),
            app_key=getattr(settings, "push_app_key", ""),
            app_secret=getattr(settings, "push_app_secret", ""),
            timeout=getattr(settings, "push_timeout", 5.0),
        )
        self.outbox = outbox or Outbox(
            getattr(settings, "outbox_path", "push_outbox.db"))

        self.running = False
        self._task = None
        self._lock = asyncio.Lock()

        self._last_track_at = 0.0
        self._last_program_ver = None
        self._last_meteo_sig = None
        self._last_alarm = None
        self._last_prune = 0.0

        self.counters = {"enqueued": 0, "sent": 0, "failed": 0, "dead": 0,
                         "skipped": 0}
        self.last_error: Optional[str] = None
        self.last_send_at: Optional[float] = None
        self.last_ok_at: Optional[float] = None

    # ------------------------------------------------------------ 生命周期
    def start(self):
        if not self.enabled:
            log.info("推送未启用（PUSH_ENABLED=false）")
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        log.info("推送服务已启动: mode=%s endpoint=%s",
                 self.client.mode, self.client.endpoint or "-")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _loop(self):
        interval = float(getattr(self.settings, "push_interval", 2.0))
        while self.running:
            try:
                self.collect()
                await self.drain()
            except Exception:  # noqa: BLE001
                log.exception("推送周期异常")
            await asyncio.sleep(interval)

    # ------------------------------------------------------------ 采集
    def collect(self, now: Optional[float] = None) -> int:
        """把当前运行态组装成消息并入队，返回新增条数。"""
        now = time.time() if now is None else now
        added = 0

        # 1) 实时态势（按间隔限流）
        interval = float(getattr(self.settings, "push_track_interval", 5.0))
        if now - self._last_track_at >= interval:
            tracks = self.traffic.snapshot() if self.traffic else []
            if tracks:
                self._last_track_at = now
                payload = adapter.track_payload(tracks)
                msg = adapter.message_for("SURVEILLANCE", self.node_id, payload, now)
                added += int(self._enqueue(msg, "traffic"))

        # 2) 飞行程序（版本变化才推）
        prog = getattr(self.store, "current_program", None)
        if prog is not None and prog.version != self._last_program_ver:
            self._last_program_ver = prog.version
            payload = adapter.program_payload(self._program_dict(prog),
                                              self.store.airport.code)
            msg = adapter.message_for("FLIGHT_PROGRAM", self.node_id, payload, now)
            added += int(self._enqueue(msg, "program"))

        # 3) 告警（有新的 last_alarm 才推一次）
        alarm = getattr(self.store, "last_alarm", None)
        if alarm and alarm != self._last_alarm:
            self._last_alarm = alarm
            payload = adapter.alert_payload(alarm, level="WARNING",
                                            airport_code=self.store.airport.code)
            msg = adapter.message_for("ALERT", self.node_id, payload, now)
            added += int(self._enqueue(msg, "alert"))

        # 4) 气象（内容变化才推）
        meteo = getattr(self.store, "meteo", None)
        if meteo is not None:
            sig = hashlib.sha1(json.dumps(meteo.__dict__, sort_keys=True,
                                          default=str).encode()).hexdigest()
            if sig != self._last_meteo_sig:
                self._last_meteo_sig = sig
                payload = adapter.meteo_payload(meteo.__dict__, self.store.airport.code)
                msg = adapter.message_for("METEO", self.node_id, payload, now)
                added += int(self._enqueue(msg, "meteo"))

        return added

    def _enqueue(self, message: dict, topic: str) -> bool:
        ok = self.outbox.enqueue(message, topic)
        if ok:
            self.counters["enqueued"] += 1
        else:
            self.counters["skipped"] += 1
        return ok

    def _program_dict(self, prog) -> dict:
        """把 ENU 航路点转成对外发布的经纬度航路。"""
        to_ll = self.store._to_latlon

        def wp(w):
            lat, lon, alt = to_ll(w.x, w.y, w.z)
            return {"lat": round(lat, 7), "lon": round(lon, 7),
                    "alt_msl": round(alt, 1), "speed": w.speed}

        return {
            "type": prog.program_type,
            "version": prog.version,
            "source": prog.source,
            "direction": getattr(prog, "direction", None),
            "std_name": getattr(prog, "std_name", None),
            "waypoints": [wp(w) for w in prog.waypoints],
            "miss_approach": [wp(w) for w in prog.miss_approach],
        }

    # ------------------------------------------------------------ 发送
    async def drain(self, force: bool = False) -> dict:
        """把到期消息发出去。返回本轮统计。"""
        if not self.enabled:
            return {"sent": 0, "failed": 0}
        async with self._lock:
            rows = self.outbox.due(limit=int(getattr(self.settings, "push_batch", 20)),
                                   force=force)
            sent = failed = 0
            for row in rows:
                res = await asyncio.to_thread(self.client.send, row["payload"])
                now = time.time()
                self.last_send_at = now
                if res.ok:
                    self.outbox.mark_sent(row["msg_id"], res.latency_ms, now)
                    self.counters["sent"] += 1
                    self.last_ok_at = now
                    sent += 1
                else:
                    status = self.outbox.mark_failed(row["msg_id"], res.error or "unknown", now)
                    self.counters["failed"] += 1
                    self.last_error = res.error
                    if status == "dead":
                        self.counters["dead"] += 1
                    failed += 1
            return {"sent": sent, "failed": failed}

    def requeue_dead(self) -> int:
        return self.outbox.requeue_dead()

    def send_test(self) -> dict:
        """立即发一条测试报文（演示/联调用）。"""
        payload = {"hello": "world", "ts": datetime.now(timezone.utc).isoformat(
            timespec="seconds")}
        msg = adapter.message_for("HEARTBEAT", self.node_id, payload)
        self.outbox.enqueue(msg, "test")
        res = self.client.send(msg)
        if res.ok:
            self.outbox.mark_sent(msg["msgId"], res.latency_ms)
        else:
            self.outbox.mark_failed(msg["msgId"], res.error or "unknown")
        return {"msg_id": msg["msgId"], "result": res.as_dict()}

    # ------------------------------------------------------------ 状态
    def status(self) -> dict:
        now = time.time()
        if now - self._last_prune > 600:
            self._last_prune = now
            try:
                self.outbox.prune()
            except Exception:  # noqa: BLE001
                pass

        q = self.outbox.stats(now)
        total = q["sent"] + q["pending"] + q["dead"]
        return {
            "enabled": self.enabled,
            "mode": self.client.mode,
            "endpoint": self.client.endpoint,
            "node_id": self.node_id,
            "running": self.running,
            "queue": q,
            "counters": dict(self.counters),
            "success_rate": round(q["sent"] / total, 3) if total else None,
            "last_error": self.last_error,
            "last_send_at": self.last_send_at,
            "last_ok_at": self.last_ok_at,
            "config": {
                "track_interval_s": getattr(self.settings, "push_track_interval", 5.0),
                "poll_interval_s": getattr(self.settings, "push_interval", 2.0),
                "batch": getattr(self.settings, "push_batch", 20),
            },
        }
