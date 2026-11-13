"""仿真引擎数据模型 — 从 src/domain/models.py 移植，无 PySide6 依赖。"""
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

    def distance_to(self, other: Vec2) -> float:
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
    battery_capacity_kwh: float = 0.0


@dataclass
class Slot:
    slot_id: str
    center: Vec2
    name: str = ""
    stand_type: str = "outdoor"
    description: str = ""
    occupied_by: Optional[str] = None
    occupied_until: float = 0.0
    footprint_radius_m: float = 14.0
    max_drone_size_m: float = 5.0
    station_charge_kw: float = 10.0
    station_charge_cap_kw: float = 10.0

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.slot_id

    @property
    def is_available(self) -> bool:
        return self.occupied_by is None


@dataclass
class RectangleZone:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, p: Vec2) -> bool:
        return self.x_min <= p.x <= self.x_max and self.y_min <= p.y <= self.y_max


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


@dataclass
class AlertRecord:
    drone_id: str
    message: str
    timestamp: float
    active: bool = True


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
    dock_charge_total_sim: float = 0.0
    soc_at_dock_start: float = 100.0
    deviation_timer: float = 0.0
    demo_route_mode: str = "follow"
    inbound_clean: bool = True
    planned_route_opacity: float = 1.0
    completed_inbound_route: Optional[Route] = None
    completed_inbound_route_opacity: float = 0.0
    assignment_rationale: Optional[str] = None
    current_speed: float = 0.0
    current_accel: float = 0.0
    battery_percent: float = 100.0
