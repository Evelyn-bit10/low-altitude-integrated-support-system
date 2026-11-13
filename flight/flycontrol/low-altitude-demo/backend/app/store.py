"""运行态存储 + 数据访问。

优先连接统一数据库(PostgreSQL/PostGIS, 生产), 不可用时回退到内置内存演示数据
(便于无 Docker 环境直接演示)。所有几何量在内存中以 ENU 米 / AGL 表示。
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlalchemy import func, select

from . import demo_data, models
from .plans_library import build_library
from .config import Settings
from .db import build_engine, build_session_factory
from .domain import (AircraftLimits, Airspace, Airport, EnvSnapshot, FlightProgram,
                     Meteo, Obstacle, Waypoint)
from .engines import geometry as geo

log = logging.getLogger("lowalt.store")


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_ok = False
        self.engine = None
        self.Session = None

        self.airport: Airport = demo_data.AIRPORT
        self.all_obstacles: List[Obstacle] = list(demo_data.OBSTACLES)
        self.active_ids = set(demo_data.ACTIVE_OBSTACLE_IDS)
        self.airspaces: List[Airspace] = list(demo_data.AIRSPACES)
        self.rules: dict = dict(demo_data.RULES)
        self.plans: List[dict] = list(demo_data.PLANS)
        # 8 方向进出场方案库（代码内置，不走 DB，避免演示库表结构迁移）
        self.plans_lib: List[dict] = build_library(self.airport.code)
        self.meteo: Meteo = demo_data.DEFAULT_METEO
        self.limits: AircraftLimits = demo_data.DEFAULT_LIMITS

        self.current_program: Optional[FlightProgram] = None
        self.risk_result = None
        self.compliance = None
        self.simulate = None
        self.version = 0
        self.last_alarm: Optional[str] = None
        self.last_event: Optional[str] = None

        self._to_enu, self._to_latlon = geo.make_converter(
            self.airport.lat, self.airport.lon, self.airport.elevation)

    # ------------------------------------------------------------------ 生命周期
    def init(self):
        try:
            self.engine = build_engine(self.settings)
            self.Session = build_session_factory(self.engine)
            models.Base.metadata.create_all(self.engine)
            self._seed_if_empty()
            self._load_from_db()
            self.db_ok = True
            log.info("数据库就绪: %s", self.settings.database_url)
        except Exception as e:  # noqa: BLE001
            log.warning("数据库不可用, 回退内存演示模式: %s", e)
            self.db_ok = False

    # ------------------------------------------------------------------ 属性
    @property
    def obstacles(self) -> List[Obstacle]:
        return [o for o in self.all_obstacles if o.id in self.active_ids]

    def snapshot(self) -> EnvSnapshot:
        """环境快照。会把"路线管理"里 kind=no_fly 的自定义区域并入限制空域，
        这样在后台加一条禁飞区，规划器下一帧就会绕开。"""
        airspaces = list(self.airspaces)
        try:
            from app.services.ledger import route_airspaces
            for a in route_airspaces():
                if not any(x.name == a.name for x in airspaces):
                    airspaces.append(a)
        except Exception:
            pass
        return EnvSnapshot(self.airport, self.obstacles, airspaces,
                           self.meteo, self.limits)

    # ------------------------------------------------------------------ 数据库
    def _seed_if_empty(self):
        with self.Session() as s:
            n = s.execute(select(func.count()).select_from(models.LpAirportPoint)).scalar_one()
            if n and n > 0:
                return
            ap = models.LpAirportPoint(
                point_name=self.airport.name, point_code=self.airport.code,
                lon=self.airport.lon, lat=self.airport.lat,
                altitude=int(self.airport.elevation), safe_radius=int(self.airport.safe_radius),
                runway_heading=self.airport.runway_heading, max_type="eVTOL")
            s.add(ap)

            for o in self.all_obstacles:
                lat, lon, alt = self._to_latlon(o.x, o.y, 0.0)
                s.add(models.LpObstacle(
                    point_code=self.airport.code, obs_name=o.name, obs_type=o.obs_type,
                    lon=lon, lat=lat,
                    base_alt=int(self.airport.elevation + o.base_agl),
                    top_alt=int(self.airport.elevation + o.top_agl),
                    radius=int(o.radius), buffer_radius=int(o.buffer),
                    status=1 if o.id in self.active_ids else 0))

            for a in self.airspaces:
                poly = [[round(self._to_latlon(x, y, 0.0)[1], 7),
                         round(self._to_latlon(x, y, 0.0)[0], 7)] for (x, y) in a.polygon]
                s.add(models.LpAirspace(space_name=a.name, poly_json=json.dumps(poly),
                                        floor_alt=int(self.airport.elevation + a.floor_agl),
                                        ceiling_alt=int(self.airport.elevation + a.ceiling_agl)))

            for k, v in self.rules.items():
                s.add(models.LpAviRule(rule_key=k, rule_value=v, rule_source="DEMO"))

            for p in self.plans:
                s.add(models.LpProgramPlan(
                    point_code=self.airport.code, plan_name=p["plan_name"],
                    plan_type=p.get("plan_type"), wind_range=p.get("wind_range"),
                    visi_range=p.get("visi_range"),
                    waypoint_json=json.dumps(p.get("waypoints", [])),
                    is_default=p.get("is_default", 0)))
            s.commit()
            log.info("已写入种子数据")

    def _load_from_db(self):
        with self.Session() as s:
            rows = s.execute(select(models.LpAviRule)).scalars().all()
            for r in rows:
                self.rules[r.rule_key] = r.rule_value
            obs = s.execute(select(models.LpObstacle)).scalars().all()
            self.all_obstacles = []
            self.active_ids = set()
            for o in obs:
                x, y, _ = self._to_enu(float(o.lat), float(o.lon), 0.0)
                base = float(o.base_alt) if o.base_alt is not None else self.airport.elevation
                top = float(o.top_alt) if o.top_alt is not None else self.airport.elevation
                ob = Obstacle(id=int(o.id), name=o.obs_name or f"障碍物{o.id}",
                              obs_type=int(o.obs_type) if o.obs_type is not None else 1,
                              x=x, y=y,
                              base_agl=base - self.airport.elevation,
                              top_agl=top - self.airport.elevation,
                              radius=float(o.radius) if o.radius is not None else 30.0,
                              buffer=float(o.buffer_radius) if o.buffer_radius is not None else 60.0)
                self.all_obstacles.append(ob)
                if o.status != 0:   # 0=停用; 其余(含 NULL)=启用
                    self.active_ids.add(ob.id)
            airs = s.execute(select(models.LpAirspace)).scalars().all()
            self.airspaces = []
            for a in airs:
                poly_ll = json.loads(a.poly_json or "[]")
                poly_enu = [(self._to_enu(lat, lon, 0.0)[0], self._to_enu(lat, lon, 0.0)[1])
                            for (lon, lat) in poly_ll]
                self.airspaces.append(Airspace(
                    id=int(a.id), name=a.space_name or "空域",
                    polygon=poly_enu,
                    floor_agl=float(a.floor_alt or 0) - self.airport.elevation,
                    ceiling_agl=float(a.ceiling_alt or 0) - self.airport.elevation))
            plans = s.execute(select(models.LpProgramPlan)).scalars().all()
            self.plans = []
            for p in plans:
                self.plans.append({
                    "id": int(p.id), "point_code": p.point_code, "plan_name": p.plan_name,
                    "plan_type": p.plan_type, "wind_range": p.wind_range,
                    "visi_range": p.visi_range,
                    "waypoints": json.loads(p.waypoint_json or "[]"),
                    "is_default": p.is_default or 0,
                })

    def save_release(self, program: FlightProgram, risk_level: int, notam: str):
        if not self.db_ok:
            return
        try:
            with self.Session() as s:
                wps = [w.as_dict() for w in program.waypoints]
                s.add(models.LpProgramRelease(
                    point_code=self.airport.code, plan_id=program.plan_id,
                    program_version=program.version,
                    program_type=1 if program.program_type != "departure" else 2,
                    waypoint_json=json.dumps(wps),
                    risk_level=risk_level, release_status=2,
                    notam_content=notam, release_time=func.now()))
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("写入发布记录失败: %s", e)

    def log_meteo(self):
        if not self.db_ok:
            return
        try:
            with self.Session() as s:
                s.add(models.LpMeteoLog(
                    point_code=self.airport.code, wind_speed=self.meteo.wind_speed,
                    wind_dir=self.meteo.wind_dir, gust=self.meteo.gust,
                    visibility=self.meteo.visibility, cloud_base=self.meteo.cloud_base,
                    turbulence_level=self.meteo.turbulence,
                    wind_shear_level=self.meteo.wind_shear,
                    temperature=self.meteo.temperature, pressure=self.meteo.pressure))
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("写入气象日志失败: %s", e)

    # ------------------------------------------------------------------ 状态操作
    def publish(self, program: FlightProgram, risk_level: int):
        self.version += 1
        program.version = f"v{self.version}"
        self.current_program = program
        notam = self._notam(program, risk_level)
        self.last_event = notam
        self.save_release(program, risk_level, notam)

    @staticmethod
    def _notam(program: FlightProgram, risk_level: int) -> str:
        kind = "进近" if program.program_type != "departure" else "离场"
        return (f"[低空动态程序] {kind}程序 {program.version} 已发布生效, "
                f"风险等级 {risk_level}, 航路点 {len(program.waypoints)} 个")

    def set_meteo(self, m: Meteo):
        self.meteo = m
        self.log_meteo()

    def toggle_obstacle(self, obs_id: int, active: bool) -> Optional[Obstacle]:
        ob = next((o for o in self.all_obstacles if o.id == obs_id), None)
        if ob is None:
            return None
        if active:
            self.active_ids.add(obs_id)
        else:
            self.active_ids.discard(obs_id)
        self._update_obstacle_status(obs_id, active)
        return ob

    def _update_obstacle_status(self, obs_id: int, active: bool):
        if not self.db_ok:
            return
        try:
            with self.Session() as s:
                row = s.get(models.LpObstacle, obs_id)
                if row:
                    row.status = 1 if active else 0
                    s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("更新障碍物状态失败: %s", e)
