"""仿真桥接模块 — 将 SimulationEngine 连接到 PyQt5 主窗口。

SimBridge 作为 QObject，用 QTimer 驱动仿真引擎的 step(dt)，
将仿真 Vec2 坐标转为 GCJ02 经纬度，并发射与现有 main_window
兼容的 telemetry 信号。
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from engine.sim_models import Drone, DroneStatus, Slot, Vec2
from engine.simulation_engine import SimulationEngine
from engine.coord_bridge import CoordBridge


class SimBridge(QObject):
    """仿真引擎 ↔ PyQt5 UI 桥接层。"""

    # 兼容现有 main_window.on_drone_telemetry(telem: dict)
    telemetryUpdated = pyqtSignal(dict)

    # 状态变更通知
    simStatusChanged = pyqtSignal(str)     # "running" / "paused" / "stopped"
    simAlertAdded = pyqtSignal(str)         # 告警消息
    simSlotChanged = pyqtSignal(list)       # 机位状态列表变化
    simDroneListChanged = pyqtSignal(list)  # 无人机列表变化
    simTimeChanged = pyqtSignal(float)      # 仿真时间

    # 航线可视化：发射航线坐标给 Leaflet
    routeUpdated = pyqtSignal(str, list)    # drone_id, [(lat, lng), ...]

    def __init__(
        self,
        engine: SimulationEngine,
        coord: CoordBridge,
        tick_ms: int = 50,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._engine = engine
        self._coord = coord
        self._tick_ms = tick_ms
        self._running = False
        self._paused = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(tick_ms)

        # 记录已渲染的航线避免重复发射
        self._rendered_routes: Dict[str, str] = {}  # drone_id -> route hash

    # ------------------------------------------------------------------
    # 控制接口
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动仿真（如果首次启动，初始化场景）。"""
        if not self._running:
            self._running = True
            self._paused = False
            self._timer.start()
            self.simStatusChanged.emit("running")

    def pause(self) -> None:
        """暂停/恢复仿真。"""
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self._timer.stop()
            self.simStatusChanged.emit("paused")
        else:
            self._timer.start()
            self.simStatusChanged.emit("running")

    def stop(self) -> None:
        """停止仿真并重置。"""
        self._timer.stop()
        self._running = False
        self._paused = False
        self._engine.reset_demo_state()
        self._rendered_routes.clear()
        self.simStatusChanged.emit("stopped")

    def reset(self) -> None:
        """重置仿真状态（不清无人机）。"""
        self._engine.reset_demo_state()
        self._rendered_routes.clear()
        self.simStatusChanged.emit("stopped")

    def step_once(self) -> None:
        """单步执行（暂停时使用）。"""
        if self._running:
            self._engine.step(self._tick_ms / 1000.0)
            self._emit_all_state()

    def set_speed(self, multiplier: float) -> None:
        """设置仿真速度倍率（1x=实时, 2x=双倍, 5x=五倍, ...）。"""
        new_interval = max(10, int(self._tick_ms / multiplier))
        self._timer.setInterval(new_interval)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def engine(self) -> SimulationEngine:
        return self._engine

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """QTimer 回调：执行一步仿真并发射状态。"""
        if not self._running or self._paused:
            return
        dt = self._tick_ms / 1000.0
        self._engine.step(dt)
        self._emit_all_state()

    def _emit_all_state(self) -> None:
        """发射当前所有无人机、航线、机位、告警的状态。"""
        self.simTimeChanged.emit(self._engine.now)

        # 发射每架无人机的遥测数据
        for drone in self._engine.drones:
            self._emit_drone_telemetry(drone)
            self._emit_route_if_changed(drone)

        # 发射机位状态
        slot_list = []
        for s in self._engine.slots:
            slot_list.append({
                "id": s.slot_id,
                "name": s.name or s.slot_id,
                "occupied_by": s.occupied_by,
                "center_gcj": list(self._coord.vec2_to_gcj02(s.center)),
            })
        self.simSlotChanged.emit(slot_list)

        # 发射无人机列表
        drone_list = []
        for d in self._engine.drones:
            lat, lng = self._coord.vec2_to_gcj02(d.position)
            drone_list.append({
                "id": d.drone_id,
                "status": d.status.value if isinstance(d.status, DroneStatus) else str(d.status),
                "lat": lat,
                "lng": lng,
                "alt": d.altitude,
                "battery": d.battery_percent,
                "assigned_slot": d.assigned_slot_id,
                "priority": d.priority,
                "demo_route_mode": d.demo_route_mode,
            })
        self.simDroneListChanged.emit(drone_list)

    def _emit_drone_telemetry(self, drone: Drone) -> None:
        """将仿真无人机转为兼容 on_drone_telemetry 的 dict（WGS84 坐标）。"""
        lat, lng = self._coord.vec2_to_wgs84(drone.position)
        telem = {
            "id": drone.drone_id,
            "name": f"{drone.drone_id} ({drone.status.value})",
            "lat": lat,
            "lng": lng,
            "alt": drone.altitude,
            "battery": drone.battery_percent,
            "sats": 16,  # 仿真固定
            "connected": True,
            # 扩展字段
            "sim_status": drone.status.value if isinstance(drone.status, DroneStatus) else str(drone.status),
            "sim_slot": drone.assigned_slot_id,
            "sim_priority": drone.priority,
            "sim_speed": round(drone.current_speed, 1),
        }
        self.telemetryUpdated.emit(telem)

    def _emit_route_if_changed(self, drone: Drone) -> None:
        """航线变化时发射 GCJ02 坐标列表给 Leaflet。"""
        route = drone.planned_route
        if not route or not route.waypoints:
            return
        route_hash = f"{len(route.waypoints)}:{drone.route_progress_idx}"
        if self._rendered_routes.get(drone.drone_id) == route_hash:
            return
        self._rendered_routes[drone.drone_id] = route_hash
        pts = self._coord.route_to_gcj02_polyline(route)
        self.routeUpdated.emit(drone.drone_id, pts)

    # ------------------------------------------------------------------
    # 场景构建：从 config dict 创建完整引擎
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict, coord: Optional[CoordBridge] = None) -> SimBridge:
        """从 demo_config.yaml 的 dict 构建 SimBridge。"""
        from engine.sim_models import (
            DroneSpec, NoFlyZone, Obstacle, RectangleZone, Slot, Vec2,
        )
        from engine.path_planner import PathPlanner
        from engine.dock_scheduler import DockScheduler
        from engine.deviation_monitor import DeviationMonitor
        from engine.alert_service import AlertService, SMTPConfig

        sim_cfg = cfg.get("simulation", {})
        zones_cfg = cfg.get("zones", {})
        path_cfg = cfg.get("path", {})
        dev_cfg = cfg.get("deviation", {})
        alert_cfg = cfg.get("alert", {})
        gcs_cfg = cfg.get("gcs", {})

        # 区域
        wz = zones_cfg.get("waiting", {})
        waiting_zone = RectangleZone(
            x_min=wz.get("x_min", -220), y_min=wz.get("y_min", -160),
            x_max=wz.get("x_max", -120), y_max=wz.get("y_max", 160),
        )
        pz = zones_cfg.get("pad", {})
        pad_zone = RectangleZone(
            x_min=pz.get("x_min", -40), y_min=pz.get("y_min", -80),
            x_max=pz.get("x_max", 120), y_max=pz.get("y_max", 80),
        )

        # 机位
        slots: List[Slot] = []
        for sc in cfg.get("slots", []):
            slots.append(Slot(
                slot_id=sc["id"],
                center=Vec2(sc["x"], sc["y"]),
                name=sc.get("name", sc["id"]),
                stand_type=sc.get("type", "outdoor"),
                footprint_radius_m=sc.get("footprint_radius_m", 14),
                max_drone_size_m=sc.get("max_drone_size_m", 5),
                station_charge_kw=sc.get("station_charge_kw", 10),
                station_charge_cap_kw=sc.get("station_charge_cap_kw", 10),
            ))

        # 障碍物
        obstacles: List[Obstacle] = []
        for oc in cfg.get("obstacles", []):
            obstacles.append(Obstacle(
                name=oc.get("name", "obs"),
                center=Vec2(oc["x"], oc["y"]),
                radius=oc.get("radius", 8),
                height=oc.get("height", 30),
            ))

        # 禁飞区
        no_fly_zones: List[NoFlyZone] = []
        for nf in cfg.get("no_fly_zones", []):
            no_fly_zones.append(NoFlyZone(
                name=nf.get("name", "nfz"),
                zone=RectangleZone(
                    x_min=nf.get("x_min", 0), y_min=nf.get("y_min", 0),
                    x_max=nf.get("x_max", 10), y_max=nf.get("y_max", 10),
                ),
                max_allowed_altitude=nf.get("max_allowed_altitude", 0),
            ))

        # 路径规划器
        inbound_entry = Vec2(
            path_cfg.get("inbound_entry", {}).get("x", -170),
            path_cfg.get("inbound_entry", {}).get("y", 30),
        )
        outbound_exit = Vec2(
            path_cfg.get("outbound_exit", {}).get("x", 190),
            path_cfg.get("outbound_exit", {}).get("y", -30),
        )
        far_exit = Vec2(
            path_cfg.get("far_exit", {}).get("x", 300),
            path_cfg.get("far_exit", {}).get("y", -200),
        )
        planner = PathPlanner(
            inbound_entry=inbound_entry,
            outbound_exit=outbound_exit,
            far_exit=far_exit,
            cruise_altitude=sim_cfg.get("cruise_altitude", 12.0),
            obstacles=obstacles,
            no_fly_zones=no_fly_zones,
            grid_step=path_cfg.get("grid_step", 10),
            spline_samples_per_segment=path_cfg.get("spline_samples_per_segment", 8),
            min_turn_radius=path_cfg.get("min_turn_radius", 18),
        )

        # 调度器
        scheduler = DockScheduler()

        # 偏航监测
        deviation_monitor = DeviationMonitor(
            distance_threshold=dev_cfg.get("distance_threshold", 18.0),
            duration_threshold_seconds=dev_cfg.get("duration_threshold_seconds", 1.2),
        )

        # 告警服务
        alert_mode = alert_cfg.get("mode", "mock")
        smtp_cfg = None
        if alert_mode == "smtp":
            sc = alert_cfg.get("smtp", {})
            smtp_cfg = SMTPConfig(
                host=sc.get("host", ""),
                port=sc.get("port", 587),
                username=sc.get("username", ""),
                password=sc.get("password", ""),
                from_email=sc.get("from_email", ""),
                to_email=sc.get("to_email", ""),
            )
        alert_service = AlertService(
            cooldown_seconds=dev_cfg.get("cooldown_seconds", 6.0),
            mode=alert_mode,
            smtp_config=smtp_cfg,
        )

        # 仿真引擎
        engine = SimulationEngine(
            waiting_zone=waiting_zone,
            pad_zone=pad_zone,
            slots=slots,
            planner=planner,
            scheduler=scheduler,
            deviation_monitor=deviation_monitor,
            alert_service=alert_service,
            cruise_altitude=sim_cfg.get("cruise_altitude", 12.0),
            dock_dwell_seconds=sim_cfg.get("dock_dwell_seconds", 5.0),
            max_concurrent_inbound=sim_cfg.get("max_concurrent_inbound", 2),
            inbound_dispatch_interval_seconds=sim_cfg.get("inbound_dispatch_interval_seconds", 0.8),
            max_concurrent_outbound=sim_cfg.get("max_concurrent_outbound", 1),
            outbound_dispatch_interval_seconds=sim_cfg.get("outbound_dispatch_interval_seconds", 0.8),
            route_fade_per_second=sim_cfg.get("route_fade_per_second", 0.35),
            trail_max_points=sim_cfg.get("trail_max_points", 180),
            no_fly_zones=no_fly_zones,
            obstacles=obstacles,
            safe_altitude_max=sim_cfg.get("safe_altitude_max", 120.0),
            charging_acceleration=sim_cfg.get("charging_acceleration", 48.0),
        )

        # 坐标桥接
        if coord is None:
            coord = CoordBridge(
                gcs_lat=gcs_cfg.get("default_lat", 29.52),
                gcs_lon=gcs_cfg.get("default_lon", 106.56),
            )

        return cls(engine=engine, coord=coord, tick_ms=int(sim_cfg.get("tick_seconds", 0.1) * 1000))

    # ------------------------------------------------------------------
    # 演示场景
    # ------------------------------------------------------------------

    def load_scenario(self, scenario_index: int) -> None:
        """加载预设演示场景。"""
        self.stop()
        count = self._engine.spawn_count if hasattr(self._engine, 'spawn_count') else 3
        speed = 18.0

        if scenario_index == 0:
            # 场景1：正常进场停靠
            self._engine.create_random_drones(count, speed)
        elif scenario_index == 1:
            # 场景2：混合优先级
            self._engine.create_random_drones(count, speed)
            for i, d in enumerate(self._engine.drones):
                d.priority = [3, 1, 5][i % 3]
        elif scenario_index == 2:
            # 场景3：单机快速演示
            self._engine.create_random_drones(1, speed)
        elif scenario_index == 3:
            # 场景4：高密度（多机排队）
            self._engine.create_random_drones(min(count + 2, 8), speed)

    def set_drone_deviate(self, drone_id: str) -> bool:
        """设置无人机偏航演示模式。"""
        drone = next((d for d in self._engine.drones if d.drone_id == drone_id), None)
        if drone and drone.status in (DroneStatus.INBOUND, DroneStatus.OUTBOUND):
            drone.demo_route_mode = "deviate"
            return True
        return False

    def set_drone_recover(self, drone_id: str) -> bool:
        """设置无人机恢复模式。"""
        drone = next((d for d in self._engine.drones if d.drone_id == drone_id), None)
        if drone and drone.status in (DroneStatus.INBOUND, DroneStatus.OUTBOUND):
            drone.demo_route_mode = "recover"
            return True
        return False

    def set_drone_follow(self, drone_id: str) -> bool:
        """强制无人机贴合路径恢复跟随。"""
        return self._engine.force_demo_route_follow(drone_id)
