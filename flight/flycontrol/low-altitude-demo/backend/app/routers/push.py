# -*- coding: utf-8 -*-
"""对外推送（UOM / 地方平台）路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _service(request: Request):
    return request.app.state.push


@router.get("/push/status")
def push_status(request: Request):
    """推送状态：队列深度、成功/失败、延迟、最近错误。"""
    return _service(request).status()


@router.post("/push/flush")
async def push_flush(request: Request):
    """立即把队列里的消息发出去（忽略退避等待），用于演示/联调。"""
    svc = _service(request)
    svc.collect()
    res = await svc.drain(force=True)
    return {"ok": True, **res, "status": svc.status()}


@router.post("/push/test")
async def push_test(request: Request):
    """发送一条测试报文（HEARTBEAT）。"""
    return _service(request).send_test()


@router.post("/push/requeue")
async def push_requeue(request: Request):
    """把 dead（重试耗尽）的消息重新放回队列。"""
    n = _service(request).requeue_dead()
    return {"ok": True, "requeued": n}
