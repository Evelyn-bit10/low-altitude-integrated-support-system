# -*- coding: utf-8 -*-
"""运行时指标：每帧耗时、计数、滑动窗口。

为什么要有它
------------
现在排障只能翻日志和看 /api/traffic/stats，看不到"每帧花多久""候选边多少"
"卡尔曼协方差有没有异常膨胀"这些关键量。演示时它是技术深度，线上它是排障刚需。

设计
----
* 只用标准库；固定长度环形缓冲，内存恒定（默认保存最近 600 帧 ≈ 10 分钟）
* 所有写入都是 O(1)，不影响主流程
* snapshot() 里算分位数，调用频率低（接口触发），可以排序
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, List


def _pct(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return round(sorted_vals[i], 3)


class Metrics:
    def __init__(self, window: int = 600) -> None:
        self._lock = threading.Lock()
        self.frame_ms: Deque[float] = deque(maxlen=window)
        self.candidates: Deque[int] = deque(maxlen=window)
        self.unique: Deque[int] = deque(maxlen=window)
        self.counters: Dict[str, float] = {}
        self.started = time.time()
        self.last_frame_at = 0.0
        self.max_tracks = 0

    # ------------------------------------------------------------ 写入
    def inc(self, name: str, n: float = 1.0) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0.0) + n

    def observe_frame(self, ms: float, edges: int, unique: int,
                      tracks: int, now: float) -> None:
        with self._lock:
            self.frame_ms.append(ms)
            self.candidates.append(edges)
            self.unique.append(unique)
            self.last_frame_at = now
            if tracks > self.max_tracks:
                self.max_tracks = tracks
            self.counters["frames"] = self.counters.get("frames", 0.0) + 1.0
            self.counters["frame_ms_total"] = self.counters.get("frame_ms_total", 0.0) + ms

    # ------------------------------------------------------------ 读取
    def snapshot(self) -> dict:
        with self._lock:
            ms = sorted(self.frame_ms)
            cand = sorted(self.candidates)
            uniq = sorted(self.unique)
            counters = dict(self.counters)
            last = self.last_frame_at
            mx = self.max_tracks
            uptime = time.time() - self.started

        frames = counters.get("frames", 0.0)
        total = counters.get("frame_ms_total", 0.0)
        return {
            "uptime_sec": round(uptime, 1),
            "frames": int(frames),
            "avg_frame_ms": round(total / frames, 3) if frames else 0.0,
            "frame_ms": {
                "p50": _pct(ms, 0.50), "p90": _pct(ms, 0.90),
                "p99": _pct(ms, 0.99), "max": _pct(ms, 1.0),
            },
            "candidates": {
                "p50": _pct(cand, 0.50), "p99": _pct(cand, 0.99),
                "max": _pct(cand, 1.0),
            },
            "unique_tracks": {
                "now": uniq[-1] if uniq else 0,
                "p50": _pct(uniq, 0.50), "max": _pct(uniq, 1.0),
            },
            "max_tracks": mx,
            "last_frame_at": last,
            "counters": {k: int(v) for k, v in counters.items() if k.startswith(("match", "create", "split", "merge", "expire", "duplicate", "error"))},
        }


METRICS = Metrics()
