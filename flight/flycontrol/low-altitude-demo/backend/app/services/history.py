# -*- coding: utf-8 -*-
"""态势历史（SQLite）。

产品分析文档「缺口二」：态势主要存在内存里，短期快照不等于完整历史，
交班复盘缺据。这里把去重后的航迹按帧落库，并保留可配置的保留期。

设计
----
    * 写入走后台线程 + 队列批量 executemany，不阻塞 ingest 主流程；
    * WAL 模式，读（看板 / 接口）与写可并发；
    * 表 traffic_history 以 (id, ts) 为主键，重复帧自动覆盖；
    * 保留期默认 24 小时，prune() 由调用方定期触发。
"""
from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic_history (
    id          TEXT NOT NULL,
    ts          REAL NOT NULL,
    phase       TEXT,
    lat         REAL,
    lon         REAL,
    alt_msl     REAL,
    speed       REAL,
    heading     REAL,
    battery_pct REAL,
    source      TEXT,
    PRIMARY KEY (id, ts)
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON traffic_history(ts);
"""


def _f(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class HistoryStore:
    def __init__(self, path: str, retention_hours: float = 24.0,
                 flush_sec: float = 1.0, max_queue: int = 5000):
        self.path = path
        self.retention_sec = max(60.0, float(retention_hours) * 3600.0)
        self.flush_sec = max(0.2, float(flush_sec))
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=max(100, int(max_queue)))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._init_db()
        self._thread = threading.Thread(target=self._run, name="history-writer", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ 初始化
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------ 写入
    def record(self, rows, now: Optional[float] = None) -> None:
        """把一帧唯一航迹投递到写队列；队列满时跳过本帧（不阻塞主流程）。"""
        ts = time.time() if now is None else float(now)
        for row in rows or []:
            try:
                rid = row.get("id")
            except AttributeError:
                continue
            if not rid:
                continue
            item = (
                str(rid), ts,
                row.get("phase"),
                _f(row.get("lat")), _f(row.get("lon")), _f(row.get("alt_msl")),
                _f(row.get("speed")), _f(row.get("heading")), _f(row.get("battery_pct")),
                str(row.get("source_node") or row.get("source") or ""),
            )
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                return

    def flush_now(self) -> int:
        """同步把队列写盘（测试与优雅关闭用）。"""
        rows = []
        while True:
            try:
                rows.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if rows:
            self._flush(rows)
        return len(rows)

    def _run(self) -> None:
        buf: List[tuple] = []
        last = time.time()
        while not self._stop.is_set():
            try:
                buf.append(self._queue.get(timeout=0.2))
            except queue.Empty:
                pass
            if buf and (len(buf) >= 200 or time.time() - last >= self.flush_sec):
                self._flush(buf)
                buf = []
                last = time.time()
        if buf:
            self._flush(buf)

    def _flush(self, rows: List[tuple]) -> None:
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO traffic_history "
                    "(id, ts, phase, lat, lon, alt_msl, speed, heading, battery_pct, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
        except Exception:
            pass

    # ------------------------------------------------------------ 查询
    def recent(self, minutes: int = 60, limit: int = 500) -> Dict[str, Any]:
        since = time.time() - max(1, int(minutes)) * 60
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT id, ts, phase, lat, lon, alt_msl, speed, heading, battery_pct, source "
                "FROM traffic_history WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                (since, max(1, int(limit))),
            )
            columns = [c[0] for c in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"minutes": int(minutes), "count": len(rows), "tracks": rows}

    def summary(self, minutes: int = 60, bucket_sec: int = 60) -> Dict[str, Any]:
        since = time.time() - max(1, int(minutes)) * 60
        bucket = max(10, int(bucket_sec))
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT CAST(ts / ? AS INTEGER) * ? AS bucket, "
                "COUNT(DISTINCT id) AS unique_tracks, COUNT(*) AS samples, "
                "AVG(battery_pct) AS avg_battery, MAX(speed) AS max_speed "
                "FROM traffic_history WHERE ts >= ? GROUP BY bucket ORDER BY bucket",
                (bucket, bucket, since),
            )
            points = [{
                "ts": row[0],
                "unique_tracks": row[1],
                "samples": row[2],
                "avg_battery": round(row[3], 1) if row[3] is not None else None,
                "max_speed": round(row[4], 1) if row[4] is not None else None,
            } for row in cur.fetchall()]
            total = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT id) FROM traffic_history WHERE ts >= ?",
                (since,),
            ).fetchone()
        return {
            "minutes": int(minutes),
            "bucket_sec": bucket,
            "points": points,
            "samples": total[0] if total else 0,
            "unique_tracks": total[1] if total else 0,
        }

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM traffic_history"
            ).fetchone()
        return {
            "rows": row[0] if row else 0,
            "oldest_ts": row[1] if row else None,
            "newest_ts": row[2] if row else None,
            "retention_hours": round(self.retention_sec / 3600.0, 1),
        }

    # ------------------------------------------------------------ 维护
    def prune(self) -> int:
        cutoff = time.time() - self.retention_sec
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM traffic_history WHERE ts < ?", (cutoff,))
            return cur.rowcount

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self.flush_now()
