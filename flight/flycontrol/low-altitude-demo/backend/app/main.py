"""FastAPI 应用入口。

启动方式:
    uvicorn app.main:app --host 0.0.0.0 --port 8082
启动后后台闭环调度自动运行(间隔由 DISPATCH_INTERVAL 控制, 默认 2 秒)。
"""
from __future__ import annotations

import asyncio
import math
import logging

log = logging.getLogger(__name__)
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .routers import program, push, traffic
from .services.dispatch import DispatchService
from .services.push_service import PushService
from .services.weather_reference import WeatherReference
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

settings = Settings.from_env()
store = Store(settings)
store.init()
store.weather_reference = WeatherReference()
dispatch = DispatchService(store)

# 交通态势存储(内存, 演示);生产落库 lp_traffic。机场原点用于后续 ENU 回显。
traffic_store = traffic.TrafficStore(settings)
traffic_store.set_origin(store.airport)

push_service = PushService(store, traffic_store, settings)

_DEFAULT_FRONTEND = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"
FRONTEND_DIR = pathlib.Path(os.getenv("FRONTEND_DIR", str(_DEFAULT_FRONTEND)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    dispatch.start()

    # 预热航道缓存（8 个方向），让第一次点击就能秒回
    async def _warm():
        try:
            from app.routers.program import warm_join_cache
            n = await asyncio.to_thread(warm_join_cache, dispatch, "arrival")
            log.info("航道缓存预热完成：%d 个方向", n)
        except Exception as exc:
            log.warning("航道缓存预热失败: %s", exc)
    asyncio.create_task(_warm())

    # 预热"点击投放"的常用点位（8 方位 × 3 个半径），让第一次点击就秒回
    # 后端自身地址用 SELF_BASE_URL 覆盖（换端口 / 换主机时不用改代码）
    async def _warm_join_points():
        import urllib.request
        await asyncio.sleep(8)
        base = os.getenv("SELF_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
        pts = []
        for deg in range(0, 360, 22):      # 16 个方位
            for r in (500, 1000, 1500, 2000, 2500):
                pts.append((r * math.sin(math.radians(deg)), r * math.cos(math.radians(deg))))
        ok = 0
        for (px, py) in pts:
            url = "%s/api/program/join?x=%.0f&y=%.0f&battery=100" % (base, px, py)
            try:
                await asyncio.to_thread(lambda u=url: urllib.request.urlopen(u, timeout=90).read())
                ok += 1
            except Exception:
                pass
        log.info("点击点位预热完成：%d/%d（约 80 个常用点位，基址 %s）", ok, len(pts), base)
    asyncio.create_task(_warm_join_points())

    async def _weather_loop():
        while True:
            await asyncio.to_thread(store.weather_reference.refresh)
            await asyncio.sleep(600)

    weather_task = asyncio.create_task(_weather_loop())
    push_service.start()
    try:
        yield
    finally:
        weather_task.cancel()
        await asyncio.gather(weather_task, return_exceptions=True)
        await push_service.stop()
        await dispatch.stop()


app = FastAPI(
    title="低空动态起降飞行程序实时调整系统 (Demo)",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.store = store
app.state.dispatch = dispatch
app.state.traffic = traffic_store
app.state.push = push_service
from app.routers import admin, ai, rl_lab, task_drafts  # noqa: E402

app.include_router(program.router, prefix="/api")
app.include_router(traffic.router, prefix="/api")
app.include_router(push.router, prefix="/api")
app.include_router(rl_lab.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(task_drafts.router, prefix="/api")

# ---- 轻量 RBAC：开启后所有写操作都要带 X-Token（见 app/services/auth.py）----
app.state.auth_enabled = bool(getattr(settings, "auth_enabled", False))


@app.middleware("http")
async def _rbac(request, call_next):
    try:
        from app.services.auth import allow, required_role, role_of
        if getattr(app.state, "auth_enabled", False):
            need = required_role(request.url.path, request.method)
            if need is not None:
                role = role_of(request.headers.get("x-token"))
                if not allow(role, need):
                    from fastapi.responses import JSONResponse
                    status = 403 if role else 401
                    if request.url.path in ("/api/ai/advice", "/api/ai/verdict", "/api/ai/follow-up", "/api/ai/reviews"):
                        ai._audit_access_denied(request.url.path.removeprefix("/api/"), status, role,
                                                "insufficient_permissions" if role else "invalid_credentials")
                    return JSONResponse(
                        {"detail": "需要 %s 权限（请在 X-Token 头里带 token）" % need},
                        status_code=status)
    except Exception:
        from fastapi.responses import JSONResponse
        if request.url.path in ("/api/ai/advice", "/api/ai/audit"):
            try:
                ai._audit_access_denied(request.url.path.removeprefix("/api/"), 503, None, "auth_check_failed")
            except Exception:
                pass
        return JSONResponse({"detail": "权限检查失败"}, status_code=503)
    return await call_next(request)


# 允许 communication 前端(含 file:// 的 null 源)跨域访问。
# 演示默认放宽；生产用 CORS_ORIGINS（逗号分隔）收紧，例如 CORS_ORIGINS=https://ops.example.com
if settings.auth_enabled and "*" in settings.cors_origins:
    log.warning("AUTH_ENABLED=1 但 CORS_ORIGINS 仍为 *；建议用 CORS_ORIGINS=https://your-host 收紧来源")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index():
    if (FRONTEND_DIR / "index.html").exists():
        return FileResponse(FRONTEND_DIR / "index.html")
    return {"message": "低空动态起降飞行程序实时调整系统 Demo", "docs": "/docs"}
