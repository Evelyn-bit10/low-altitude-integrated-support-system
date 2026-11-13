# -*- coding: utf-8 -*-
"""推送发件箱（Outbox）。

为什么要落库而不是内存队列：
  - 断网 / 对端故障时消息不能丢；
  - 进程重启后仍能续传；
  - 重试次数、下次重试时间、失败原因都可查。

实现：标准库 sqlite3（不依赖 ORM 与额外服务），单连接 + 线程锁。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

__all__ = ["Outbox"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS push_outbox (
    msg_id      TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending / sent / dead
    attempts    INTEGER NOT NULL DEFAULT 0,
    next_retry  REAL NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  REAL NOT NULL,
    sent_at     REAL,
    latency_ms  REAL
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON push_outbox(status, next_retry);
"""


class Outbox:
    def __init__(self, path: str = "push_outbox.db", max_attempts: int = 8):
        self.path = path
        self.max_attempts = int(max_attempts)
        self._lock = threading.Lock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------ 写入
    def enqueue(self, message: dict, topic: str, now: Optional[float] = None) -> bool:
        """入队一条消息；msgId 已存在则跳过（幂等）。"""
        now = time.time() if now is None else now
        msg_id = message.get("msgId")
        if not msg_id:
            raise ValueError("message 缺少 msgId")
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO push_outbox"
                "(msg_id, topic, payload, status, attempts, next_retry, created_at)"
                " VALUES (?,?,?,'pending',0,?,?)",
                (msg_id, topic, json.dumps(message, ensure_ascii=False), now, now))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------ 读取
    def due(self, now: Optional[float] = None, limit: int = 20,
            force: bool = False) -> List[dict]:
        """取出待发消息（按创建时间先后）。force=True 时忽略重试等待时间。"""
        now = time.time() if now is None else now
        with self._lock:
            if force:
                rows = self._conn.execute(
                    "SELECT * FROM push_outbox WHERE status='pending'"
                    " ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM push_outbox WHERE status='pending' AND next_retry<=?"
                    " ORDER BY created_at ASC LIMIT ?", (now, limit)).fetchall()
        return [{"msg_id": r["msg_id"], "topic": r["topic"],
                 "payload": json.loads(r["payload"]), "attempts": r["attempts"]}
                for r in rows]

    # ------------------------------------------------------------ 状态更新
    def mark_sent(self, msg_id: str, latency_ms: float = 0.0,
                  now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._conn.execute(
                "UPDATE push_outbox SET status='sent', sent_at=?, latency_ms=?,"
                " last_error=NULL WHERE msg_id=?", (now, latency_ms, msg_id))
            self._conn.commit()

    def mark_failed(self, msg_id: str, error: str,
                    now: Optional[float] = None) -> str:
        """记一次失败；返回新状态（pending=稍后重试 / dead=放弃）。"""
        now = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM push_outbox WHERE msg_id=?", (msg_id,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            if attempts >= self.max_attempts:
                status, next_retry = "dead", now
            else:
                status = "pending"
                next_retry = now + min(60.0, 2.0 ** attempts)   # 指数退避
            self._conn.execute(
                "UPDATE push_outbox SET status=?, attempts=?, next_retry=?, last_error=?"
                " WHERE msg_id=?", (status, attempts, next_retry, str(error)[:500], msg_id))
            self._conn.commit()
            return status

    def requeue_dead(self) -> int:
        """把 dead 的消息重新放回队列（人工重试用）。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE push_outbox SET status='pending', attempts=0, next_retry=0"
                " WHERE status='dead'")
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------ 维护 / 统计
    def prune(self, keep_sent_days: float = 1.0, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        cut = now - keep_sent_days * 86400.0
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM push_outbox WHERE status='sent' AND sent_at<?", (cut,))
            self._conn.commit()
            return cur.rowcount

    def stats(self, now: Optional[float] = None) -> Dict:
        now = time.time() if now is None else now
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n, AVG(latency_ms) AS lat,"
                " MAX(sent_at) AS last_ok FROM push_outbox GROUP BY status").fetchall()
            last_err = self._conn.execute(
                "SELECT last_error FROM push_outbox WHERE last_error IS NOT NULL"
                " ORDER BY created_at DESC LIMIT 1").fetchone()
            pending_due = self._conn.execute(
                "SELECT COUNT(*) AS n FROM push_outbox WHERE status='pending' AND next_retry<=?",
                (now,)).fetchone()["n"]
            oldest = self._conn.execute(
                "SELECT MIN(created_at) AS t FROM push_outbox WHERE status='pending'"
            ).fetchone()["t"]

        by = {r["status"]: r["n"] for r in rows}
        latency = next((r["lat"] for r in rows if r["status"] == "sent"), None)
        last_ok = next((r["last_ok"] for r in rows if r["status"] == "sent"), None)
        return {
            "pending": by.get("pending", 0),
            "sent": by.get("sent", 0),
            "dead": by.get("dead", 0),
            "due_now": pending_due,
            "oldest_pending_age_s": round(now - oldest, 1) if oldest else 0.0,
            "avg_latency_ms": round(latency, 1) if latency is not None else None,
            "last_success_at": last_ok,
            "last_error": last_err["last_error"] if last_err else None,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
