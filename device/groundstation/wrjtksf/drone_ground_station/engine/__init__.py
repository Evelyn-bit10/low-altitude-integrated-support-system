"""仿真引擎包 — 从 src/ 迁移的路径规划、调度、偏航监测、仿真实时等模块。"""
from engine.sim_models import (
    Drone, DroneSpec, DroneStatus, Slot, Vec2, Waypoint, Route,
    RectangleZone, Obstacle, NoFlyZone, AlertRecord,
)
from engine.simulation_engine import SimulationEngine
from engine.path_planner import PathPlanner
from engine.dock_scheduler import DockScheduler
from engine.deviation_monitor import DeviationMonitor
from engine.alert_service import AlertService, SMTPConfig
from engine.geo_math import world_meters_to_wgs84, wgs84_to_world_meters
