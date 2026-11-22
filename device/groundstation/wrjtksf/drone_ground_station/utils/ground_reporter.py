# -*- coding: utf-8 -*-
"""地面站 → 门户数据桥的上报线程（不阻塞 UI）。

背景
----
    产品分析文档「缺口一」：门户数据桥原来只有正弦波模拟，拿不到地面站真实状态。
    现在由地面站主窗口定期收集机位 / 传感器 / RID 状态，投递给本线程 POST 到
    `http://<host>:8090/api/ground/report`；数据桥优先使用上报值，过期后自动回退模拟。

设计
----
    * QThread + 队列（只保留最新一帧），网络请求不在主线程；
    * 失败静默（数据桥没启动时不影响地面站），下一轮自动重试；
    * 超时 2 秒，避免线程卡死。
"""
from __future__ import annotations

import json
import queue
import urllib.request

from PyQt5.QtCore import QThread


class GroundReporter(QThread):
    """把地面站状态 POST 给数据桥。"""

    def __init__(self, url: str, interval_ms: int = 2000, parent=None):
        super().__init__(parent)
        self._url = str(url).rstrip("/") + "/api/ground/report"
        self._interval = max(500, int(interval_ms))
        self._queue = queue.Queue(maxsize=1)
        self._running = True
        # 本机上报不走系统代理（Clash 等开启时 urllib 会误把 127.0.0.1 也代理掉）
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------ 对外
    def submit(self, payload: dict) -> None:
        """投递一帧最新状态；队列满时丢弃旧帧，保证总是最新的。"""
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                pass

    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    # ------------------------------------------------------------ 线程体
    def run(self) -> None:
        while self._running:
            try:
                payload = self._queue.get(timeout=self._interval / 1000.0)
            except queue.Empty:
                continue
            if payload is None:
                break
            try:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    self._url,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                self._opener.open(req, timeout=2).read()
            except Exception:
                # 数据桥未启动 / 网络不可用时静默，下轮重试
                pass
