from __future__ import annotations

import random
from typing import Dict, List, Optional

from src.domain.models import (
    Drone,
    DroneSpec,
    DroneStatus,
    NoFlyZone,
    Obstacle,
    RectangleZone,
    Slot,
    Vec2,
    Waypoint,
)
from src.engine.deviation_monitor import DeviationMonitor
from src.engine.dock_scheduler import DockScheduler
from src.engine.path_planner import PathPlanner
from src.engine.slot_policy import (
    charge_time_seconds,
    effective_charge_kw,
    new_slot_overlaps_existing,
    resolved_battery_kwh,
    slot_accepts_drone,
)
from src.services.alert_service import AlertService


class SimulationEngine:
    def __init__(
        self,
        waiting_zone: RectangleZone,
        pad_zone: RectangleZone,
        slots: List[Slot],
        planner: PathPlanner,
        scheduler: DockScheduler,
        deviation_monitor: DeviationMonitor,
        alert_service: AlertService,
        cruise_altitude: float,
        dock_dwell_seconds: float,
        max_concurrent_inbound: int = 2,
        inbound_dispatch_interval_seconds: float = 0.8,
        max_concurrent_outbound: int = 1,
        outbound_dispatch_interval_seconds: float = 0.8,
        route_fade_per_second: float = 0.35,
        trail_max_points: int = 180,
        no_fly_zones: Optional[List[NoFlyZone]] = None,
        obstacles: Optional[List[Obstacle]] = None,
        safe_altitude_max: float = 120.0,
        charging_acceleration: float = 5.0,
    ) -> None:
        self.waiting_zone = waiting_zone
        self.pad_zone = pad_zone
        self.slots = slots
        self.planner = planner
        self.scheduler = scheduler
        self.deviation_monitor = deviation_monitor
        self.alert_service = alert_service
        self.cruise_altitude = cruise_altitude
        self.dock_dwell_seconds = dock_dwell_seconds
        self.max_concurrent_inbound = max(1, max_concurrent_inbound)
        self.inbound_dispatch_interval_seconds = max(0.0, inbound_dispatch_interval_seconds)
        self.max_concurrent_outbound = max(1, max_concurrent_outbound)
        self.outbound_dispatch_interval_seconds = max(0.0, outbound_dispatch_interval_seconds)
        self.route_fade_per_second = max(0.0, route_fade_per_second)
        self.trail_max_points = max(20, trail_max_points)
        self.no_fly_zones = no_fly_zones or []
        self.obstacles = obstacles or []
        self.safe_altitude_max = safe_altitude_max
        # 充电加速因子：演示充电时长 = 真实充电时长 / charging_acceleration
        # 例如：真实需要 30 分钟，加速因子为 5.0，则演示中只需 6 分钟
        self.charging_acceleration = max(1.0, float(charging_acceleration))
        self._recover_route_join_m = 3.0
        self.drones: List[Drone] = []
        self.now: float = 0.0
        self.alert_feed: List[str] = []
        self.last_inbound_dispatch_at: float = -1e9
        self.last_outbound_dispatch_at: float = -1e9

    def create_random_drones(self, count: int, speed: float) -> None:
        self.drones = []
        size_cycle = [0.85, 1.15, 1.55, 2.05, 2.65, 3.1]
        power_cycle = [3.2, 4.8, 7.5, 11.0, 15.0, 20.0]
        for i in range(count):
            y = random.uniform(-200, 200)
            x = random.uniform(-340, -260)
            sz = size_cycle[i % len(size_cycle)]
            pk = power_cycle[i % len(power_cycle)]
            drone = Drone(
                drone_id=f"D{i + 1}",
                position=Vec2(x, y),
                altitude=self.cruise_altitude,
                speed=speed,
                spec=DroneSpec(
                    model=f"Demo-{sz:.1f}m",
                    size=float(sz),
                    required_power=float(pk),
                    max_speed=max(25.0, speed * 1.5),
                    max_accel=18.0,
                    battery_capacity_kwh=0.0,
                ),
            )
            drone.battery_percent = random.uniform(42.0, 96.0)
            drone.history.append(Waypoint(drone.position, drone.altitude))
            self.drones.append(drone)

    def add_mission_drone(
        self,
        drone_id: str,
        model: str,
        size: float,
        required_power: float,
        battery_capacity_kwh: float,
        priority: int,
        battery_percent: float = 100.0,  # 新增参数：无人机当前电量百分比（0-100），用于计算停靠时长
    ) -> tuple[bool, str]:
        if any(d.drone_id == drone_id for d in self.drones):
            return False, f"分配失败：无人机ID {drone_id} 已存在"
        spec = DroneSpec(
            model=model,
            size=float(size),
            required_power=float(required_power),
            max_speed=26.0,
            max_accel=16.0,
            battery_capacity_kwh=float(max(0.0, battery_capacity_kwh)),
        )
        # 创建探测用的临时无人机对象，用于机位分配算法
        probe = Drone(
            drone_id=drone_id,
            position=Vec2(self.waiting_zone.x_min, 0),
            altitude=self.cruise_altitude,
            speed=18.0,
            spec=spec,
        )
        # 设置探测无人机的电量，用于计算预计停靠时长
        probe.battery_percent = battery_percent
        slot = self.scheduler.assign_slot(probe, self.slots, self.now)
        if not slot:
            return False, "分配失败：无可用机位（尺寸/占用不匹配或全部占用）"

        # 生成机位分配原因说明（包含优先级、停靠时长、Best-Fit 匹配等信息）
        rationale = self.scheduler.describe_assignment(probe, slot, self.slots, self.now)

        spawn_y = random.uniform(self.waiting_zone.y_min + 5, self.waiting_zone.y_max - 5)
        drone = Drone(
            drone_id=drone_id,
            position=Vec2(self.waiting_zone.x_min - 20, spawn_y),
            altitude=self.cruise_altitude,
            speed=18.0,
            spec=spec,
            priority=priority,
            expected_dock_seconds=0.0,
        )
        # 设置真实无人机的初始电量
        drone.battery_percent = battery_percent
        # 保存分配原因说明，用于 UI 显示
        drone.assignment_rationale = rationale or None
        drone.assigned_slot_id = slot.slot_id
        slot.occupied_by = drone_id
        slot.occupied_until = self.now + 1.0e9
        drone.history.append(Waypoint(drone.position, drone.altitude))
        self.drones.append(drone)
        return True, f"分配成功：机位 {slot.slot_id}"

    def remove_drone(self, drone_id: str) -> tuple[bool, str]:
        drone = next((d for d in self.drones if d.drone_id == drone_id), None)
        if drone is None:
            return False, "无人机不存在"
        if drone.status in (
            DroneStatus.INBOUND,
            DroneStatus.DOCKED,
            DroneStatus.WAITING_OUTBOUND,
            DroneStatus.OUTBOUND,
        ):
            return False, "当前状态不可移除（需在接近或等待区等待阶段）"
        for s in self.slots:
            if s.occupied_by == drone_id:
                s.occupied_by = None
                s.occupied_until = 0.0
        drone.assigned_slot_id = None
        self.drones.remove(drone)
        return True, "已移除无人机"

    def release_stand_assignment(self, drone_id: str) -> tuple[bool, str]:
        drone = next((d for d in self.drones if d.drone_id == drone_id), None)
        if drone is None:
            return False, "无人机不存在"
        if drone.status not in (DroneStatus.APPROACHING, DroneStatus.WAITING):
            return False, "仅在地面前等待状态可释放预约机位"
        sid = drone.assigned_slot_id
        if not sid:
            return False, "未预约机位"
        slot = self._get_slot(sid)
        if slot and slot.occupied_by == drone_id:
            slot.occupied_by = None
            slot.occupied_until = 0.0
        drone.assigned_slot_id = None
        return True, "已释放机位预约"

    def manual_assign_slot(self, drone_id: str, slot_id: str) -> tuple[bool, str]:
        drone = next((d for d in self.drones if d.drone_id == drone_id), None)
        if drone is None:
            return False, "无人机不存在"
        slot = self._get_slot(slot_id)
        if slot is None:
            return False, "机位不存在"
        if not slot_accepts_drone(slot, drone, self.now):
            return False, "该机位最大尺寸不足以容纳此无人机"
        avail = slot.occupied_by is None or slot.occupied_until <= self.now or slot.occupied_by == drone_id
        if not avail:
            return False, "机位已被其他无人机占用"
        old = drone.assigned_slot_id
        if old and old != slot_id:
            olds = self._get_slot(old)
            if olds and olds.occupied_by == drone_id:
                olds.occupied_by = None
                olds.occupied_until = 0.0
        drone.assigned_slot_id = slot_id
        slot.occupied_by = drone_id
        slot.occupied_until = self.now + 1.0e9
        return True, f"已分配机位 {slot_id}"

    def add_slot(self, slot: Slot) -> tuple[bool, str]:
        if not self.pad_zone.contains(slot.center):
            return False, "机位中心必须在机场规定区域（停机坪矩形）内"
        if any(s.slot_id == slot.slot_id for s in self.slots):
            return False, "机位 ID 已存在"
        conflict = new_slot_overlaps_existing(slot, self.slots)
        if conflict:
            return False, f"机位保护区与已有 {conflict} 重叠，请调整中心或缩小半径"
        self.slots.append(slot)
        return True, "机位已添加"

    def remove_slot(self, slot_id: str) -> tuple[bool, str]:
        slot = self._get_slot(slot_id)
        if slot is None:
            return False, "机位不存在"
        if slot.occupied_by:
            return False, "机位占用中，无法删除"
        self.slots[:] = [s for s in self.slots if s.slot_id != slot_id]
        return True, "机位已删除"

    def force_release_slot(self, slot_id: str) -> tuple[bool, str]:
        """释放机位占用（与机位卡「释放」一致）：清空占用，并解除仍在等待阶段的无人机的预约。"""
        slot = self._get_slot(slot_id)
        if slot is None:
            return False, "机位不存在"
        occ = slot.occupied_by
        slot.occupied_by = None
        slot.occupied_until = 0.0
        if occ:
            for d in self.drones:
                if d.drone_id == occ and d.assigned_slot_id == slot_id:
                    if d.status in (DroneStatus.APPROACHING, DroneStatus.WAITING):
                        d.assigned_slot_id = None
        return True, "机位已释放"

    def reset_demo_state(self) -> None:
        """清空所有仿真无人机、机位占用与仿真时钟，用于演示场景切换。"""
        self.drones.clear()
        for s in self.slots:
            s.occupied_by = None
            s.occupied_until = 0.0
        self.now = 0.0
        self.alert_feed.clear()
        self.last_inbound_dispatch_at = -1e9
        self.last_outbound_dispatch_at = -1e9
        self.alert_service.reset_session()

    def _get_slot(self, slot_id: Optional[str]) -> Optional[Slot]:
        if not slot_id:
            return None
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None

    def _move_toward_waypoint(self, drone: Drone, dt: float) -> None:
        if not drone.planned_route or drone.route_progress_idx >= len(drone.planned_route.waypoints):
            return
        target = drone.planned_route.waypoints[drone.route_progress_idx]
        dx = target.position.x - drone.position.x
        dy = target.position.y - drone.position.y
        dist = (dx * dx + dy * dy) ** 0.5
        max_step = drone.speed * dt
        if dist <= max_step or dist == 0:
            drone.position = Vec2(target.position.x, target.position.y)
            drone.altitude = target.altitude
            drone.route_progress_idx += 1
            return

        ratio = max_step / dist
        drone.position = Vec2(
            drone.position.x + dx * ratio,
            drone.position.y + dy * ratio,
        )
        drone.altitude = drone.altitude + (target.altitude - drone.altitude) * ratio

    def _move_demo_deviate(self, drone: Drone, dt: float) -> None:
        """偏航演示：不沿航点推进，侧向脱离规划折线。"""
        if not drone.planned_route:
            drone.demo_route_mode = "follow"
            return
        u = self.deviation_monitor.escape_unit_from_route(drone.position, drone.planned_route)
        step = max(0.0, drone.speed * dt)
        drone.position = Vec2(drone.position.x + u.x * step, drone.position.y + u.y * step)
        pr = drone.planned_route
        if drone.route_progress_idx < len(pr.waypoints):
            tgt_alt = pr.waypoints[drone.route_progress_idx].altitude
            blend = min(1.0, step / max(8.0, self._recover_route_join_m * 2.0))
            drone.altitude += (tgt_alt - drone.altitude) * blend

    def _snap_route_progress_after_recover(self, drone: Drone, seg_i: int) -> None:
        n = len(drone.planned_route.waypoints) if drone.planned_route else 0
        if n < 2:
            drone.route_progress_idx = 0
            return
        drone.route_progress_idx = min(seg_i + 1, n - 1)

    def _move_demo_recover(self, drone: Drone, dt: float) -> None:
        """飞回规划路径最近点，到达容差后恢复沿航点飞行。"""
        if not drone.planned_route:
            drone.demo_route_mode = "follow"
            return
        closest, seg_i, t = self.deviation_monitor.closest_on_route(drone.position, drone.planned_route)
        dx = closest.x - drone.position.x
        dy = closest.y - drone.position.y
        dist = (dx * dx + dy * dy) ** 0.5
        step = max(0.0, drone.speed * dt)
        join = self._recover_route_join_m
        wps = drone.planned_route.waypoints
        if dist <= join or dist < 1e-9:
            drone.position = Vec2(closest.x, closest.y)
            ha = wps[seg_i].altitude * (1.0 - t) + wps[seg_i + 1].altitude * t
            drone.altitude = float(ha)
            self._snap_route_progress_after_recover(drone, seg_i)
            drone.demo_route_mode = "follow"
            drone.deviation_timer = 0.0
            return
        ratio = step / dist
        drone.position = Vec2(drone.position.x + dx * ratio, drone.position.y + dy * ratio)
        ha = wps[seg_i].altitude * (1.0 - t) + wps[seg_i + 1].altitude * t
        drone.altitude += (float(ha) - drone.altitude) * min(1.0, ratio * 3.0)

    def force_demo_route_follow(self, drone_id: str) -> bool:
        """立即贴合规划路径并恢复沿路径飞行（演示中再次点击「恢复」时可用）。"""
        drone = next((d for d in self.drones if d.drone_id == drone_id), None)
        if drone is None or not drone.planned_route:
            return False
        if drone.status not in (DroneStatus.INBOUND, DroneStatus.OUTBOUND):
            return False
        closest, seg_i, t = self.deviation_monitor.closest_on_route(drone.position, drone.planned_route)
        drone.position = Vec2(closest.x, closest.y)
        wps = drone.planned_route.waypoints
        ha = wps[seg_i].altitude * (1.0 - t) + wps[seg_i + 1].altitude * t
        drone.altitude = float(ha)
        self._snap_route_progress_after_recover(drone, seg_i)
        drone.demo_route_mode = "follow"
        drone.deviation_timer = 0.0
        return True

    def _assign_and_plan_inbound(self, drone: Drone) -> None:
        slot = self.scheduler.assign_slot(drone, self.slots, self.now)
        if not slot:
            drone.status = DroneStatus.WAITING
            return
        slot.occupied_by = drone.drone_id
        slot.occupied_until = self.now + self.dock_dwell_seconds + 1000.0
        drone.assigned_slot_id = slot.slot_id
        drone.planned_route = self.planner.plan_inbound(drone.position, slot.center)
        drone.route_progress_idx = 0
        drone.demo_route_mode = "follow"
        drone.inbound_clean = True
        drone.planned_route_opacity = 1.0
        drone.completed_inbound_route = None
        drone.completed_inbound_route_opacity = 0.0
        drone.status = DroneStatus.INBOUND
        self.last_inbound_dispatch_at = self.now

    def _can_start_outbound(self, current_inbound_count: int, current_outbound_count: int) -> bool:
        """
        判断是否可以开始出场
        修改说明：移除了 current_inbound_count == 0 的限制，允许进场和出场同时进行
        """
        return (
            current_outbound_count < self.max_concurrent_outbound
            and (self.now - self.last_outbound_dispatch_at) >= self.outbound_dispatch_interval_seconds
        )

    def _mark_route_arrived(self, drone: Drone) -> bool:
        return bool(drone.planned_route and drone.route_progress_idx >= len(drone.planned_route.waypoints))

    def _nudge_route_progress_if_near_terminal(self, drone: Drone, terminal_radius_m: float = 18.0) -> None:
        """脱离/恢复演示时 route_progress 可能不递增，若已接近航线终点则视为走完全程。"""
        if drone.demo_route_mode not in ("deviate", "recover"):
            return
        if not drone.planned_route or len(drone.planned_route.waypoints) < 1:
            return
        end = drone.planned_route.waypoints[-1].position
        if drone.position.distance_to(end) < terminal_radius_m:
            drone.route_progress_idx = len(drone.planned_route.waypoints)

    def step(self, dt: float) -> None:
        self.now += dt
        current_inbound_count = sum(1 for d in self.drones if d.status == DroneStatus.INBOUND)
        current_outbound_count = sum(1 for d in self.drones if d.status == DroneStatus.OUTBOUND)

        # 按优先级排序处理无人机（优先级高的先处理）
        # 修改说明：确保高优先级无人机优先获得机位分配和派遣机会
        sorted_drones = sorted(self.drones, key=lambda d: -d.priority)

        for drone in sorted_drones:
            prev = Vec2(drone.position.x, drone.position.y)
            prev_speed = drone.current_speed
            if drone.status == DroneStatus.FINISHED:
                continue

            if drone.status == DroneStatus.APPROACHING:
                # Let approaching drones drift slowly toward waiting zone.
                drone.position = Vec2(drone.position.x + drone.speed * dt * 0.6, drone.position.y)
                if self.waiting_zone.contains(drone.position):
                    drone.in_waiting_zone = True
                    drone.waiting_since = self.now
                    drone.status = DroneStatus.WAITING

            elif drone.status == DroneStatus.WAITING:
                # 判断是否可以派遣进场
                # 修改说明：移除了 current_outbound_count == 0 的限制，允许进场和出场同时进行
                can_dispatch = (
                    current_inbound_count < self.max_concurrent_inbound
                    and (self.now - self.last_inbound_dispatch_at) >= self.inbound_dispatch_interval_seconds
                )
                if can_dispatch:
                    self._assign_and_plan_inbound(drone)
                    if drone.status == DroneStatus.INBOUND:
                        current_inbound_count += 1

            elif drone.status == DroneStatus.INBOUND:
                if drone.demo_route_mode == "deviate":
                    self._move_demo_deviate(drone, dt)
                elif drone.demo_route_mode == "recover":
                    self._move_demo_recover(drone, dt)
                else:
                    self._move_toward_waypoint(drone, dt)
                self._nudge_route_progress_if_near_terminal(drone)
                if self._mark_route_arrived(drone):
                    drone.demo_route_mode = "follow"
                    drone.status = DroneStatus.DOCKED
                    drone.altitude = 0.0
                    drone.soc_at_dock_start = drone.battery_percent
                    slot_d = self._get_slot(drone.assigned_slot_id)
                    if drone.spec and slot_d:
                        p_kw = effective_charge_kw(slot_d, drone.spec)
                        kwh = resolved_battery_kwh(drone.spec)
                        t_real = charge_time_seconds(drone.battery_percent, kwh, p_kw)
                        drone.dock_charge_total_sim = max(t_real / self.charging_acceleration, 0.05)
                    else:
                        drone.dock_charge_total_sim = max(self.dock_dwell_seconds / self.charging_acceleration, 0.05)
                    drone.dwell_time_remaining = drone.dock_charge_total_sim
                    if drone.inbound_clean and drone.planned_route:
                        drone.completed_inbound_route = drone.planned_route
                        drone.completed_inbound_route_opacity = 1.0
                    drone.planned_route = None
                    drone.planned_route_opacity = 0.0

            elif drone.status == DroneStatus.DOCKED:
                drone.altitude = 0.0
                tot = max(drone.dock_charge_total_sim, 1e-6)
                drone.dwell_time_remaining -= dt
                prog = 1.0 - max(0.0, drone.dwell_time_remaining) / tot
                prog = max(0.0, min(1.0, prog))
                drone.battery_percent = min(
                    100.0,
                    drone.soc_at_dock_start + (100.0 - drone.soc_at_dock_start) * prog,
                )
                if drone.dwell_time_remaining <= 0.0:
                    drone.battery_percent = 100.0
                    drone.status = DroneStatus.WAITING_OUTBOUND

            elif drone.status == DroneStatus.WAITING_OUTBOUND:
                # 充满电后等待出场许可
                if self._can_start_outbound(current_inbound_count, current_outbound_count):
                    slot = self._get_slot(drone.assigned_slot_id)
                    if slot:
                        slot.occupied_until = self.now
                        # 修改说明：起飞时立即释放机位，让其他无人机可以使用
                        # 原逻辑在 OUTBOUND 结束时释放，导致已离开的无人机仍占用机位
                        if slot.occupied_by == drone.drone_id:
                            slot.occupied_by = None
                            slot.occupied_until = 0.0
                    drone.assigned_slot_id = None
                    drone.planned_route = self.planner.plan_outbound(drone.position)
                    drone.route_progress_idx = 0
                    drone.demo_route_mode = "follow"
                    drone.planned_route_opacity = 1.0
                    drone.status = DroneStatus.OUTBOUND
                    self.last_outbound_dispatch_at = self.now
                    current_outbound_count += 1

            elif drone.status == DroneStatus.OUTBOUND:
                if drone.demo_route_mode == "deviate":
                    self._move_demo_deviate(drone, dt)
                elif drone.demo_route_mode == "recover":
                    self._move_demo_recover(drone, dt)
                else:
                    self._move_toward_waypoint(drone, dt)
                self._nudge_route_progress_if_near_terminal(drone)
                if self._mark_route_arrived(drone):
                    drone.demo_route_mode = "follow"
                    drone.status = DroneStatus.FINISHED

            if drone.status in (DroneStatus.INBOUND, DroneStatus.OUTBOUND):
                deviated = self.deviation_monitor.check_deviation(drone, dt)
                if deviated and drone.planned_route:
                    dist = self.deviation_monitor.min_route_distance(drone.position, drone.planned_route)
                    msg = self.alert_service.trigger_deviation_alert(drone.drone_id, self.now, dist)
                    self.alert_feed.append(f"t={self.now:.1f}s {drone.drone_id}: {msg}")
                    if drone.status == DroneStatus.INBOUND:
                        drone.inbound_clean = False

            travel = prev.distance_to(drone.position)
            drone.current_speed = travel / dt if dt > 0 else 0.0
            drone.current_accel = abs(drone.current_speed - prev_speed) / dt if dt > 0 else 0.0

            for zone in self.no_fly_zones:
                if zone.zone.contains(drone.position) and drone.altitude <= zone.max_allowed_altitude:
                    msg = self.alert_service.trigger_event_alert(
                        drone.drone_id,
                        self.now,
                        "no-fly-zone",
                        f"entered {zone.name}, z={drone.altitude:.1f}m",
                    )
                    self.alert_feed.append(f"t={self.now:.1f}s {drone.drone_id}: {msg}")

            if drone.altitude > self.safe_altitude_max:
                msg = self.alert_service.trigger_event_alert(
                    drone.drone_id,
                    self.now,
                    "altitude",
                    f"altitude {drone.altitude:.1f} > limit {self.safe_altitude_max:.1f}",
                )
                self.alert_feed.append(f"t={self.now:.1f}s {drone.drone_id}: {msg}")
            if drone.spec and drone.current_speed > drone.spec.max_speed:
                msg = self.alert_service.trigger_event_alert(
                    drone.drone_id,
                    self.now,
                    "speed",
                    f"speed {drone.current_speed:.1f} > limit {drone.spec.max_speed:.1f}",
                )
                self.alert_feed.append(f"t={self.now:.1f}s {drone.drone_id}: {msg}")
            if drone.spec and drone.current_accel > drone.spec.max_accel:
                msg = self.alert_service.trigger_event_alert(
                    drone.drone_id,
                    self.now,
                    "accel",
                    f"accel {drone.current_accel:.1f} > limit {drone.spec.max_accel:.1f}",
                )
                self.alert_feed.append(f"t={self.now:.1f}s {drone.drone_id}: {msg}")

            if drone.completed_inbound_route and drone.completed_inbound_route_opacity > 0.0:
                drone.completed_inbound_route_opacity = max(
                    0.0, drone.completed_inbound_route_opacity - self.route_fade_per_second * dt
                )
            if drone.status in (DroneStatus.INBOUND, DroneStatus.OUTBOUND):
                drone.planned_route_opacity = 1.0
            elif drone.planned_route:
                drone.planned_route_opacity = max(0.0, drone.planned_route_opacity - self.route_fade_per_second * dt)
                if drone.planned_route_opacity <= 0.0:
                    drone.planned_route = None

            drone.history.append(Waypoint(Vec2(drone.position.x, drone.position.y), drone.altitude))
            if len(drone.history) > self.trail_max_points:
                overflow = len(drone.history) - self.trail_max_points
                drone.history = drone.history[overflow:]

            # 电量消耗逻辑
            # 修改说明：WAITING_OUTBOUND 状态不消耗电量，保持充满电状态
            # 只有飞行中的无人机（APPROACHING, WAITING, INBOUND, OUTBOUND）才消耗电量
            if drone.status not in (DroneStatus.FINISHED, DroneStatus.DOCKED, DroneStatus.WAITING_OUTBOUND):
                drone.battery_percent = max(0.0, drone.battery_percent - dt * 0.12)

    def snapshot(self) -> Dict[str, object]:
        return {
            "time": self.now,
            "drones": self.drones,
            "slots": self.slots,
            "obstacles": self.obstacles,
            "no_fly_zones": self.no_fly_zones,
            "alerts": self.alert_service.records,
            "alert_feed": self.alert_feed[-20:],
        }
