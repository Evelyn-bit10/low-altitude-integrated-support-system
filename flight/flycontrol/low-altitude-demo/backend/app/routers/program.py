"""对外 API 路由。"""
from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..services.weather_reference import locate_weather

from ..domain import Meteo
from ..plans_library import find_plans
from ..schemas import GenerateRequest, MeteoUpdate, ObstacleToggle, ReplanRequest
from ..engines.planner import DIRECTIONS, DIRECTION_CN

router = APIRouter()


def _serialize_program(program):
    if program is None:
        return None
    return {
        "version": program.version,
        "type": program.program_type,
        "source": program.source,
        "plan_id": program.plan_id,
        "direction": getattr(program, "direction", None),
        "std_name": getattr(program, "std_name", None),
        "waypoints": [w.as_dict() for w in program.waypoints],
        "miss_approach": [w.as_dict() for w in program.miss_approach],
    }


def _compliance_dict(comp):
    if comp is None:
        return None
    return {
        "passed": comp.passed,
        "checks": [{"name": c.name, "pass": c.passed, "detail": c.detail,
                    "margin": c.margin} for c in comp.checks],
    }


def _sim_dict(sim):
    if sim is None:
        return None
    return {"passed": sim.passed, "checks": sim.checks}


def _risk_dict(rr):
    if rr is None:
        return None
    return {"score": rr.score, "level": rr.level, "level_name": rr.level_name,
            "factors": rr.factors, "program_status": rr.program_status,
            "matched_plan_id": rr.matched_plan_id}


@router.get("/health")
def health(request: Request):
    store = request.app.state.store
    return {"status": "ok", "db_ok": store.db_ok, "version": store.version}


@router.get("/airport")
def airport(request: Request):
    a = request.app.state.store.airport
    return {"code": a.code, "name": a.name, "lat": a.lat, "lon": a.lon,
            "elevation": a.elevation, "runway_heading": a.runway_heading}


@router.get("/obstacles")
def obstacles(request: Request):
    store = request.app.state.store
    return [
        {"id": o.id, "name": o.name, "obs_type": o.obs_type, "x": round(o.x, 1),
         "y": round(o.y, 1), "top_agl": round(o.top_agl, 1), "radius": o.radius,
         "buffer": o.buffer, "active": o.id in store.active_ids}
        for o in store.all_obstacles
    ]


@router.get("/airspaces")
def airspaces(request: Request):
    return [
        {"id": a.id, "name": a.name, "polygon": [[round(x, 1), round(y, 1)] for x, y in a.polygon],
         "floor_agl": a.floor_agl, "ceiling_agl": a.ceiling_agl}
        for a in request.app.state.store.airspaces
    ]


@router.get("/rules")
def rules(request: Request):
    return request.app.state.store.rules


@router.get("/program/current")
def program_current(request: Request):
    store = request.app.state.store
    return {
        "program": _serialize_program(store.current_program),
        "risk": _risk_dict(store.risk_result),
        "compliance": _compliance_dict(store.compliance),
        "simulate": _sim_dict(store.simulate),
        "meteo": store.meteo.__dict__,
        "alarm": store.last_alarm,
        "last_event": store.last_event,
    }


@router.post("/program/replan")
async def program_replan(request: Request, body: ReplanRequest):
    service = request.app.state.dispatch
    prog, comp, sim = await asyncio.to_thread(
        service.run_manual_replan, body.program_type, body.direction)
    return {"program": _serialize_program(prog),
            "compliance": _compliance_dict(comp), "simulate": _sim_dict(sim)}


@router.get("/plans")
def list_plans(request: Request, program_type: str = "arrival",
               direction: str | None = None):
    """方案库查询：按类型（arrival/departure）与方向筛选。"""
    store = request.app.state.store
    plans = find_plans(store.plans_lib, program_type, direction)
    return {
        "point_code": store.airport.code,
        "program_type": program_type,
        "direction": direction,
        "directions": [{"name": k, "cn": DIRECTION_CN[k], "bearing": v}
                       for k, v in DIRECTIONS.items()],
        "plans": plans,
    }


@router.post("/program/generate")
async def program_generate(request: Request, body: GenerateRequest):
    """按方向生成进出场程序（方案库直出 / 动态重规划）。"""
    service = request.app.state.dispatch
    prog, comp, sim, meta = await asyncio.to_thread(
        service.run_generate, body.program_type, body.direction, body.mode)
    return {"program": _serialize_program(prog),
            "compliance": _compliance_dict(comp), "simulate": _sim_dict(sim),
            "meta": meta}


class DeviceLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


@router.post("/weather/device")
def device_weather(body: DeviceLocation):
    return locate_weather(body.latitude, body.longitude)


@router.get("/weather/reference")
def weather_reference(request: Request):
    service = getattr(request.app.state.store, "weather_reference", None)
    return service.snapshot() if service else {"status": "unavailable", "reason": "not_configured", "data": None}


@router.post("/env/meteo")
def env_meteo(request: Request, body: MeteoUpdate):
    store = request.app.state.store
    store.set_meteo(Meteo(**body.model_dump()))
    return {"ok": True, "meteo": store.meteo.__dict__}


@router.post("/env/obstacle/toggle")
def env_obstacle_toggle(request: Request, body: ObstacleToggle):
    store = request.app.state.store
    ob = store.toggle_obstacle(body.id, body.active)
    if ob is None:
        return {"ok": False, "msg": f"障碍物 {body.id} 不存在"}
    return {"ok": True, "id": ob.id, "name": ob.name, "active": body.active}


@router.get("/program/recommend")
async def program_recommend(request: Request, program_type: str = "arrival",
                            heading: float | None = None):
    """自动推荐进出场方向：把 8 个方向都生成一遍，按可解释规则打分排序。

    评分见 `app/services/recommend.py`：硬约束淘汰 → 侧风(0.25) + 航程(0.20)
    + 梯度余量(0.10) + 航向契合(0.05) + 基础分(0.40)。
    """
    import asyncio
    from app.plans_library import DIRECTIONS as DIRS
    from app.services import recommend as rec

    service = request.app.state.dispatch
    store = request.app.state.store
    env = store.snapshot()

    results = []
    for d, bearing in DIRS.items():
        prog, comp, sim, meta = await asyncio.to_thread(
            service.run_generate, program_type, d, "template")
        # 该方向的"进场/着陆"航向：进场取方位+180，离场取方位本身
        hdg = (float(bearing) + 180.0) % 360.0 if program_type != "departure" else float(bearing)
        row = rec.score_one(d, float(bearing), prog, comp, sim, env.meteo, hdg)
        row["entry_heading"] = hdg
        row["mode"] = meta.get("mode")
        row["fallback"] = meta.get("fallback", False)
        results.append(row)

    ranked = rec.rank(results, None if heading is None else float(heading))
    best = ranked[0] if ranked else None
    return {
        "program_type": program_type,
        "wind": {"speed": env.meteo.wind_speed, "dir": env.meteo.wind_dir},
        "recommend": best["direction"] if best else None,
        "reason": best["reasons"] if best else [],
        "ranking": [{"direction": r["direction"], "score": r["score"],
                     "available": r["available"], "metrics": r["metrics"],
                     "reasons": r["reasons"]} for r in ranked],
    }


@router.get("/program/choose")
async def program_choose(request: Request, x: float, y: float,
                         program_type: str = "arrival"):
    """无人机出现在任意位置时，自动选择进场/离场航道。

    参数 x, y 是相对起降点的 ENU 坐标（米，东正、北正）。
    返回：该方位对应的最近方向、距离、以及推荐理由和航迹点。
    """
    import asyncio
    import math
    from app.plans_library import DIRECTIONS
    from app.services import recommend as rec

    r = math.hypot(x, y)
    bearing = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0 if r > 1e-6 else 0.0

    # 最近的 8 方向
    best_dir, best_diff = None, 999.0
    for d, b in DIRECTIONS.items():
        diff = abs((bearing - float(b) + 180.0) % 360.0 - 180.0)
        if diff < best_diff:
            best_dir, best_diff = d, diff

    service = request.app.state.dispatch
    store = request.app.state.store
    env = store.snapshot()

    prog, comp, sim, meta = await asyncio.to_thread(
        service.run_generate, program_type, best_dir, "template")
    hdg = (float(DIRECTIONS[best_dir]) + 180.0) % 360.0 if program_type != "departure" else float(DIRECTIONS[best_dir])
    row = rec.score_one(best_dir, float(DIRECTIONS[best_dir]), prog, comp, sim, env.meteo, hdg)

    # 该方位与风向的关系，作为补充理由
    delta = abs((env.meteo.wind_dir - hdg + 180.0) % 360.0 - 180.0)
    headwind = env.meteo.wind_speed * math.cos(math.radians(delta))

    return {
        "x": round(x, 1), "y": round(y, 1),
        "distance_m": round(r, 1),
        "bearing": round(bearing, 1),
        "direction": best_dir,
        "direction_offset": round(best_diff, 1),
        "available": bool(comp.is_pass and sim.is_pass),
        "mode": meta.get("mode"),
        "std_name": getattr(prog, "std_name", None),
        "headwind_mps": round(headwind, 1),
        "reason": [
            "无人机方位 %.0f°（距起降点 %.0f m）" % (bearing, r),
            "选取最近的方向 %s（相差 %.0f°）" % (best_dir, best_diff),
            "该方向 %.1f m/s %s" % (abs(headwind), "逆风" if headwind >= 0 else "顺风"),
        ] + (rec.rank([row])[0]["reasons"] if row.get("available") else ["该方向不可用"]),
        "waypoints": [{"x": w.x, "y": w.y, "z": w.z} for w in (getattr(prog, "waypoints", []) or [])],
    }


@router.get("/program/assess")
async def program_assess(request: Request, direction: str = "NW",
                         program_type: str = "arrival", battery: float = 100.0):
    """评估一条航道的「安全可达性」：安全(L1) + 能量(L2) + 退路(L3)。"""
    import asyncio
    from app.services import route_energy

    service = request.app.state.dispatch
    store = request.app.state.store
    env = store.snapshot()
    prog, comp, sim, meta = await asyncio.to_thread(
        service.run_generate, program_type, direction, "template")
    r = route_energy.assess_route(prog, env, battery_pct=float(battery))
    segs = r["segments"]
    return {
        "direction": direction,
        "std_name": getattr(prog, "std_name", None),
        "battery": battery,
        "verdict": r["verdict"],
        "ok": r["ok"],
        "reasons": r["reasons"],
        "metrics": r["metrics"],
        "segments": segs[::max(1, len(segs) // 60)][:60],
    }


@router.get("/program/best")
async def program_best(request: Request, battery: float = 100.0,
                       program_type: str = "arrival"):
    """在**当前环境 + 剩余电量**下，从 8 个方向里选出最佳航道。

    和 /program/recommend 的区别：这里把「安全可达性」作为**前置过滤**——
    先淘汰不安全/电量不够/退路丢失的方向，再在剩下的里按余量排序。
    """
    import asyncio
    from app.plans_library import DIRECTIONS
    from app.services import recommend as rec
    from app.services import route_energy

    service = request.app.state.dispatch
    store = request.app.state.store
    env = store.snapshot()

    rows = []
    for d, bearing in DIRECTIONS.items():
        prog, comp, sim, meta = await asyncio.to_thread(
            service.run_generate, program_type, d, "template")
        hdg = (float(bearing) + 180.0) % 360.0 if program_type != "departure" else float(bearing)
        base = rec.score_one(d, float(bearing), prog, comp, sim, env.meteo, hdg)
        ra = route_energy.assess_route(prog, env, battery_pct=float(battery))
        rows.append({
            "direction": d,
            "std_name": getattr(prog, "std_name", None),
            "verdict": ra["verdict"],
            "feasible": bool(base.get("available") and ra["ok"]),
            "energy_margin": ra["metrics"].get("margin", 0.0),
            "need_wh": ra["metrics"].get("need_wh", 0.0),
            "available_wh": ra["metrics"].get("available_wh", 0.0),
            "min_clearance": ra["metrics"].get("min_clearance"),
            "max_xwind": ra["metrics"].get("max_xwind"),
            "wind_score": base.get("xw_score", 0.0),
            "reasons": ra["reasons"][-2:],
        })

    feasible = [r for r in rows if r["feasible"]]
    for r in feasible:
        # 综合分：能量余量(主) + 安全余度 + 风(次)
        clr = r["min_clearance"] or 0.0
        r["score"] = round(0.5 * max(0.0, min(1.0, r["energy_margin"]))
                           + 0.3 * min(1.0, clr / 300.0)
                           + 0.2 * r["wind_score"], 3)
    feasible.sort(key=lambda r: -r["score"])
    rows.sort(key=lambda r: (not r["feasible"], -r["score"] if "score" in r else 0))

    best = feasible[0] if feasible else None
    return {
        "battery": battery,
        "verdict": best["verdict"] if best else "NONE",
        "best": best,
        "ranking": rows,
        "summary": ("推荐 %s（%s），能量余量 %.0f%%，最小超障 %s m"
                    % (best["direction"], best["std_name"],
                       best["energy_margin"] * 100, best["min_clearance"]))
        if best else "当前电量下没有任何方向可以安全到达",
    }


_JOIN_GEN_CACHE = {}          # (方向, 气象签名, 类型) -> (prog, comp, sim)


def warm_join_cache(service, program_type: str = "arrival") -> int:
    """启动时预热：把 8 个方向的程序先生成好，点击时就能秒回。"""
    import time as _t
    from app.plans_library import DIRECTIONS
    store = service.store
    wind = store.meteo
    wx_sig = (round(float(wind.wind_speed), 1), round(float(wind.wind_dir), 0),
              round(float(getattr(wind, "precipitation", 0.0)), 1))
    n = 0
    t0 = _t.perf_counter()
    for d in DIRECTIONS:
        ckey = (d, wx_sig, program_type)
        if ckey in _JOIN_GEN_CACHE:
            continue
        try:
            prog, comp, sim, _m = service.run_generate(program_type, d, "template")
            _JOIN_GEN_CACHE[ckey] = (prog, comp, sim, _m)
            n += 1
        except Exception:
            continue
    return n


_JOIN_RESP_CACHE = {}          # 点击结果缓存（20 m 网格），重复/相近位置秒回
_JOIN_CACHE_MAX = 800


def _wx_key(request):
    try:
        m = request.app.state.store.snapshot().meteo
        return (round(float(m.wind_speed), 1), round(float(m.wind_dir)),
                round(float(getattr(m, "precipitation", 0.0)), 1))
    except Exception:
        return (0.0, 0.0, 0.0)


@router.get("/program/join")
async def program_join(request: Request, x: float, y: float,
                       program_type: str = "arrival", battery: float = 100.0):
    key = (round(x / 20.0) * 20, round(y / 20.0) * 20,
           round(battery / 5.0) * 5, program_type, _wx_key(request))
    hit = _JOIN_RESP_CACHE.get(key)
    if hit is not None:
        return hit
    resp = await _join_impl(request, x, y, program_type, battery)
    if isinstance(resp, dict) and len(_JOIN_RESP_CACHE) < _JOIN_CACHE_MAX:
        _JOIN_RESP_CACHE[key] = resp
    return resp


async def _join_impl(request: Request, x: float, y: float,
                     program_type: str = "arrival", battery: float = 100.0):
    """从任意位置「接续」到航道模板：返回**不穿障碍/限飞区**的最近接入点。

    B 方案（接续）的核心难点：无人机从点击位置飞向模板的那一段直线，
    如果不管障碍物就一定会穿。这里对模板上每个航路点做直线安全性检查
    （超障余度 + 限空域），只接受"这段接续不会撞"的接入点。
    """
    import asyncio
    import math
    from app.engines import geometry as geo
    from app.engines.planner import _in_restricted
    from app.plans_library import DIRECTIONS

    service = request.app.state.dispatch
    store = request.app.state.store
    env = store.snapshot()

    from app.services import route_energy, recommend as rec

    r = math.hypot(x, y)
    bearing = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0 if r > 1e-6 else 0.0

    # ---- 环境感知的方向选择：风 / 雨 / 电量 共同决定，而不是"方位最近" ----
    wind = env.meteo
    wx_sig = (round(float(wind.wind_speed), 1), round(float(wind.wind_dir), 0),
              round(float(getattr(wind, "precipitation", 0.0)), 1))

    # 只评估"方位最近的 3 个方向"：8 个全算要 2 秒，3 个约 0.6 秒，精度损失很小
    ranked_dirs = sorted(DIRECTIONS.items(),
                         key=lambda kv: abs((bearing - float(kv[1]) + 180.0) % 360.0 - 180.0))[:3]

    cands = []
    for d, b in ranked_dirs:
        ckey = (d, wx_sig, program_type)
        if ckey in _JOIN_GEN_CACHE:
            prog_i, comp_i, sim_i, _mi = _JOIN_GEN_CACHE[ckey]
        else:
            prog_i, comp_i, sim_i, _mi = await asyncio.to_thread(
                service.run_generate, program_type, d, "template")
            _JOIN_GEN_CACHE[ckey] = (prog_i, comp_i, sim_i, _mi)
            if len(_JOIN_GEN_CACHE) > 64:
                _JOIN_GEN_CACHE.clear()
        hdg = (float(b) + 180.0) % 360.0 if program_type != "departure" else float(b)
        ra = route_energy.assess_route(prog_i, env, battery_pct=float(battery))
        base = rec.score_one(d, float(b), prog_i, comp_i, sim_i, wind, hdg)
        diff = abs((bearing - float(b) + 180.0) % 360.0 - 180.0)
        wps_i = list(getattr(prog_i, "waypoints", []) or [])
        length = sum(math.hypot(q.x - p_.x, q.y - p_.y)
                     for p_, q in zip(wps_i, wps_i[1:])) if len(wps_i) > 1 else 0.0
        cands.append({
            "dir": d, "prog": prog_i, "comp": comp_i, "sim": sim_i,
            "ok": bool(ra["ok"]), "margin": ra["metrics"].get("margin", 0.0),
            "wind": base.get("xw_score", 0.0), "length": length,
            "diff": diff, "verdict": ra["verdict"],
        })

    feasible = [c for c in cands if c["ok"]]
    if feasible:
        lmax = max(c["length"] for c in feasible) or 1.0
        for c in feasible:
            # 方位惩罚（方案 D）：偏角越大扣得越多
            #   偏 0°  罚 0    偏 45° 罚 0.15   偏 90° 罚 0.30
            # 这样"点西北就飞 NW"，但 NW 明显不安全时仍会被更好的方向压过
            penalty = 0.30 * min(c["diff"], 90.0) / 90.0
            c["penalty"] = penalty
            c["score"] = (0.35 * max(0.0, min(1.0, c["margin"]))
                          + 0.25 * c["wind"]
                          + 0.20 * (1.0 - c["length"] / lmax)
                          - penalty)
        pick = max(feasible, key=lambda c: c["score"])
        env_note = "按环境择优（风 %.1f m/s / 雨 %.1f mm/h / 电量 %.0f%%）" % (
            wind.wind_speed, getattr(wind, "precipitation", 0.0), battery)
    else:
        pick = min(cands, key=lambda c: c["diff"])
        bad = sorted({c["verdict"] for c in cands})
        env_note = "⚠ 当前环境无可用航道（%s），仅按方位退回 %s，实际不可飞" % (
            "/".join(bad), pick["dir"])

    best_dir = pick["dir"]
    best_diff = pick["diff"]
    prog, comp, sim = pick["prog"], pick["comp"], pick["sim"]
    meta = {"mode": "environment-aware"}
    wps = list(getattr(prog, "waypoints", []) or [])
    if len(wps) < 2:
        from fastapi import HTTPException
        raise HTTPException(400, "该方向没有可用航迹")

    moc = float(store.rules.get("MOC_APPROACH", 75.0))

    def leg_ok(wp) -> bool:
        a = (x, y, float(wp.z))
        b = (wp.x, wp.y, float(wp.z))
        if not geo.segment_free(a, b, env.obstacles, moc):
            return False
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 50.0) + 1)
        for i in range(n + 1):
            t = i / n
            px = a[0] + (b[0] - a[0]) * t
            py = a[1] + (b[1] - a[1]) * t
            pz = a[2] + (b[2] - a[2]) * t
            if _in_restricted(px, py, pz, getattr(env, "airspaces", None)):
                return False
        return True

    # 只允许接续到"不比自己更远离跑道"的航路点，避免出现"往回飞"
    # （无人机在 1.2 km 处，就不该接到 2 km 外的入口点再折回来）
    r_now = math.hypot(x, y)
    limit = r_now + 200.0

    best_i, best_d = None, 1e18
    for i, wp in enumerate(wps):
        if math.hypot(wp.x, wp.y) > limit:      # 比当前位置更远离跑道 → 跳过
            continue
        d = math.hypot(wp.x - x, wp.y - y)
        if d < best_d and leg_ok(wp):
            best_d, best_i = d, i

    # 兜底：如果所有点都更远（比如点在航道外侧），退化为最近的点
    if best_i is None:
        for i, wp in enumerate(wps):
            d = math.hypot(wp.x - x, wp.y - y)
            if d < best_d and leg_ok(wp):
                best_d, best_i = d, i

    if best_i is None:                       # 没有安全的接续段
        best_i = min(range(len(wps)), key=lambda i: math.hypot(wps[i].x - x, wps[i].y - y))
        best_d = math.hypot(wps[best_i].x - x, wps[best_i].y - y)
        safe = False
    else:
        safe = True

    return {
        "direction": best_dir,
        "available": bool(feasible),
        "env_note": env_note,
        "candidates": sorted([{"dir": c["dir"], "ok": c["ok"], "verdict": c["verdict"],
                               "margin": round(c["margin"], 3),
                               "wind": round(c["wind"], 3),
                               "score": round(c.get("score", 0.0), 3)} for c in cands],
                             key=lambda c: -c["score"]),
        "std_name": getattr(prog, "std_name", None),
        # 注意：这里原来是第二个 "available"，会覆盖上面的可行性字段（dict 后者覆盖前者），
        # 导致"有可用方向却报 available=False"。改成独立字段 program_ok。
        "program_ok": bool(comp.is_pass and sim.is_pass),
        "join_index": best_i,
        "join_point": {"x": round(wps[best_i].x, 1), "y": round(wps[best_i].y, 1),
                       "z": round(wps[best_i].z, 1)},
        "join_distance": round(best_d, 1),
        "join_safe": safe,
        "reason": ("接续段不穿越障碍/限飞区" if safe
                   else "没有安全的接续点，已退化为最近点（可能穿越障碍）"),
        "waypoints": [{"x": w.x, "y": w.y, "z": w.z} for w in wps],
    }


@router.get("/program/templates")
async def program_templates(request: Request, program_type: str = "arrival"):
    """一次返回 8 个方向的航道模板（含完整航迹），供可视化对比。

    每条包含：方向、标准程序名、来源（模板/动态重规划）、是否可用、航路点、航程。
    """
    import asyncio
    from app.plans_library import DIRECTIONS

    service = request.app.state.dispatch
    store = request.app.state.store
    wind = store.meteo
    wx_sig = (round(float(wind.wind_speed), 1), round(float(wind.wind_dir), 0),
              round(float(getattr(wind, "precipitation", 0.0)), 1))
    out = []
    for d, bearing in DIRECTIONS.items():
        ckey = (d, wx_sig, program_type)
        if ckey in _JOIN_GEN_CACHE:
            prog, comp, sim, meta = _JOIN_GEN_CACHE[ckey]
        else:
            prog, comp, sim, meta = await asyncio.to_thread(
                service.run_generate, program_type, d, "template")
            _JOIN_GEN_CACHE[ckey] = (prog, comp, sim, meta)
        wps = list(getattr(prog, "waypoints", []) or [])
        length = sum(math.hypot(q.x - p.x, q.y - p.y)
                     for p, q in zip(wps, wps[1:])) if len(wps) > 1 else 0.0
        out.append({
            "direction": d,
            "bearing": float(bearing),
            "std_name": getattr(prog, "std_name", None),
            "mode": meta.get("mode"),
            "fallback": bool(meta.get("fallback")),
            "available": bool(comp.is_pass and sim.is_pass),
            "points": len(wps),
            "length_m": round(length, 1),
            "waypoints": [{"x": w.x, "y": w.y, "z": w.z} for w in wps],
        })
    return {"program_type": program_type, "count": len(out), "templates": out}
