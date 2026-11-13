from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class DroneStatus(str, Enum):
    APPROACHING = "approaching"
    WAITING = "waiting"
    INBOUND = "inbound"
    DOCKED = "docked"
    WAITING_OUTBOUND = "waiting_outbound"
    OUTBOUND = "outbound"
    FINISHED = "finished"


@dataclass
class Vec2:
    x: float
    y: float

    def distance_to(self, other: "Vec2") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5


@dataclass
class Waypoint:
    position: Vec2
    altitude: float


@dataclass
class Route:
    waypoints: List[Waypoint]
    route_type: str


@dataclass
class DroneSpec:
    model: str
    size: float
    required_power: float
    max_speed: float
    max_accel: float
    # 电池容量 kWh；为 0 时由尺寸在运行时估算（演示）
    battery_capacity_kwh: float = 0.0


@dataclass
class Slot:
    slot_id: str
    center: Vec2
    name: str = ""
    stand_type: str = "outdoor"  # "indoor" | "outdoor"
    description: str = ""
    occupied_by: Optional[str] = None
    occupied_until: float = 0.0
    footprint_radius_m: float = 14.0  # 圆形保护区半径(m)，地图防重叠
    max_drone_size_m: float = 5.0  # 允许的最大无人机尺寸(m)
    station_charge_kw: float = 10.0  # 机位可用充电功率(kW)
    station_charge_cap_kw: float = 10.0  # 充电功率上限(kW)

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.slot_id

    @property
    def is_available(self) -> bool:
        return self.occupied_by is None


@dataclass
class Drone:
    drone_id: str
    position: Vec2
    altitude: float
    speed: float
    spec: Optional[DroneSpec] = None
    priority: int = 1
    expected_dock_seconds: float = 0.0
    status: DroneStatus = DroneStatus.APPROACHING
    assigned_slot_id: Optional[str] = None
    planned_route: Optional[Route] = None
    route_progress_idx: int = 0
    history: List[Waypoint] = field(default_factory=list)
    in_waiting_zone: bool = False
    waiting_since: Optional[float] = None
    dwell_time_remaining: float = 0.0
    """本次停靠充电总时长(仿真加速后的计时)，用于进度。"""
    dock_charge_total_sim: float = 0.0
    soc_at_dock_start: float = 100.0
    deviation_timer: float = 0.0
    # 偏航演示：follow=沿规划路径；deviate=主动脱离路径（不瞬移）；recover=飞回路径后再 follow
    demo_route_mode: str = "follow"
    inbound_clean: bool = True
    planned_route_opacity: float = 1.0
    completed_inbound_route: Optional[Route] = None
    completed_inbound_route_opacity: float = 0.0
    current_speed: float = 0.0
    current_accel: float = 0.0
    battery_percent: float = 100.0
    assignment_rationale: Optional[str] = None
    """加入场景时机位调度说明（演示实况旁白，只写一次）。"""

    def charging_power_watts(self, slot: Optional["Slot"] = None) -> float:
        """停靠时有效充电功率（kW→W）；需传入当前机位以计算 min(机位, 无人机需求)。"""
        if self.status != DroneStatus.DOCKED or self.spec is None:
            return 0.0
        if slot is None:
            return max(0.0, float(self.spec.required_power) * 1000.0)
        from src.engine.slot_policy import effective_charge_kw

        return effective_charge_kw(slot, self.spec) * 1000.0


@dataclass
class RectangleZone:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, point: Vec2) -> bool:
        return (
            self.x_min <= point.x <= self.x_max
            and self.y_min <= point.y <= self.y_max
        )


@dataclass
class AlertRecord:
    drone_id: str
    message: str
    timestamp: float
    active: bool = True


@dataclass
class Obstacle:
    name: str
    center: Vec2
    radius: float
    height: float


@dataclass
class NoFlyZone:
    name: str
    zone: RectangleZone
    max_allowed_altitude: float
