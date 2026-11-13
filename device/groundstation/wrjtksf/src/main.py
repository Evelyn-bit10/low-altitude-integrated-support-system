from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from src.config_loader import load_config
from src.domain.models import NoFlyZone, Obstacle, RectangleZone, Slot, Vec2
from src.engine.deviation_monitor import DeviationMonitor
from src.engine.dock_scheduler import DockScheduler
from src.engine.path_planner import PathPlanner
from src.engine.simulation_engine import SimulationEngine
from src.services.alert_service import AlertService, SMTPConfig
from src.ui.main_window import MainWindow


def build_engine(
    config_path: Path,
) -> tuple[
    SimulationEngine,
    RectangleZone,
    RectangleZone,
    list[Slot],
    list[Obstacle],
    list[NoFlyZone],
    float,
    float,
    str | None,
    dict,
]:
    cfg = load_config(config_path)

    waiting = RectangleZone(**cfg["zones"]["waiting"])
    pad = RectangleZone(**cfg["zones"]["pad"])
    slots = [
        Slot(
            slot_id=str(item["id"]),
            center=Vec2(float(item["x"]), float(item["y"])),
            name=str(item.get("name", "")),
            stand_type=str(item.get("type", item.get("stand_type", "outdoor"))),
            description=str(item.get("description", "")),
            footprint_radius_m=float(item.get("footprint_radius_m", 14.0)),
            max_drone_size_m=float(item.get("max_drone_size_m", 5.0)),
            station_charge_kw=float(item.get("station_charge_kw", item.get("max_charge_kw", 10.0))),
            station_charge_cap_kw=float(
                item.get("station_charge_cap_kw", item.get("station_charge_kw", item.get("max_charge_kw", 10.0)))
            ),
        )
        for item in cfg["slots"]
    ]
    obstacles = [
        Obstacle(
            name=item["name"],
            center=Vec2(item["x"], item["y"]),
            radius=float(item["radius"]),
            height=float(item["height"]),
        )
        for item in cfg.get("obstacles", [])
    ]
    no_fly_zones = [
        NoFlyZone(
            name=item["name"],
            zone=RectangleZone(
                x_min=float(item["x_min"]),
                y_min=float(item["y_min"]),
                x_max=float(item["x_max"]),
                y_max=float(item["y_max"]),
            ),
            max_allowed_altitude=float(item["max_allowed_altitude"]),
        )
        for item in cfg.get("no_fly_zones", [])
    ]
    surveillance_radius = float(cfg.get("map", {}).get("surveillance_radius", 170.0))
    background_image = cfg.get("map", {}).get("background_image")
    tick_seconds = float(cfg["simulation"]["tick_seconds"])

    planner = PathPlanner(
        inbound_entry=Vec2(cfg["path"]["inbound_entry"]["x"], cfg["path"]["inbound_entry"]["y"]),
        outbound_exit=Vec2(cfg["path"]["outbound_exit"]["x"], cfg["path"]["outbound_exit"]["y"]),
        far_exit=Vec2(cfg["path"]["far_exit"]["x"], cfg["path"]["far_exit"]["y"]),
        cruise_altitude=float(cfg["simulation"]["cruise_altitude"]),
        obstacles=obstacles,
        no_fly_zones=no_fly_zones,
        grid_step=float(cfg.get("path", {}).get("grid_step", 10.0)),
        spline_samples_per_segment=int(cfg.get("path", {}).get("spline_samples_per_segment", 8)),
        min_turn_radius=float(cfg.get("path", {}).get("min_turn_radius", 18.0)),
    )
    scheduler = DockScheduler()
    deviation = DeviationMonitor(
        distance_threshold=float(cfg["deviation"]["distance_threshold"]),
        duration_threshold=float(cfg["deviation"]["duration_threshold_seconds"]),
    )

    smtp_cfg = cfg["alert"]["smtp"]
    smtp = SMTPConfig(
        host=smtp_cfg["host"],
        port=int(smtp_cfg["port"]),
        username=smtp_cfg["username"],
        password=smtp_cfg["password"],
        from_email=smtp_cfg["from_email"],
        to_email=smtp_cfg["to_email"],
    )
    alert_service = AlertService(
        cooldown_seconds=float(cfg["deviation"]["cooldown_seconds"]),
        mode=cfg["alert"]["mode"],
        smtp_config=smtp,
    )

    engine = SimulationEngine(
        waiting_zone=waiting,
        pad_zone=pad,
        slots=slots,
        planner=planner,
        scheduler=scheduler,
        deviation_monitor=deviation,
        alert_service=alert_service,
        cruise_altitude=float(cfg["simulation"]["cruise_altitude"]),
        dock_dwell_seconds=float(cfg["simulation"]["dock_dwell_seconds"]),
        max_concurrent_inbound=int(cfg["simulation"].get("max_concurrent_inbound", 2)),
        inbound_dispatch_interval_seconds=float(cfg["simulation"].get("inbound_dispatch_interval_seconds", 0.8)),
        max_concurrent_outbound=int(cfg["simulation"].get("max_concurrent_outbound", 1)),
        outbound_dispatch_interval_seconds=float(cfg["simulation"].get("outbound_dispatch_interval_seconds", 0.8)),
        route_fade_per_second=float(cfg["simulation"].get("route_fade_per_second", 0.35)),
        trail_max_points=int(cfg["simulation"].get("trail_max_points", 180)),
        no_fly_zones=no_fly_zones,
        obstacles=obstacles,
        safe_altitude_max=float(cfg["simulation"].get("safe_altitude_max", 120.0)),
        charging_acceleration=float(cfg["simulation"].get("charging_acceleration", 35.0)),
    )
    engine.create_random_drones(
        count=int(cfg["simulation"]["spawn_count"]),
        speed=float(cfg["simulation"]["speed"]),
    )
    gcs_cfg = cfg.get("gcs") or {}
    return engine, waiting, pad, slots, obstacles, no_fly_zones, surveillance_radius, tick_seconds, background_image, gcs_cfg


def main() -> int:
    app = QApplication(sys.argv)
    base = QFont()
    base.setPointSize(10)
    base.setFamilies(["Times New Roman", "SimSun", "Microsoft YaHei", "serif"])
    app.setFont(base)
    root = Path(__file__).resolve().parent.parent
    config_path = root / "config" / "demo_config.yaml"
    engine, waiting, pad, slots, obstacles, no_fly_zones, surveillance_radius, tick_seconds, background_image, gcs_cfg = (
        build_engine(config_path)
    )
    window = MainWindow(
        engine,
        waiting,
        pad,
        slots,
        obstacles,
        no_fly_zones,
        surveillance_radius,
        background_image,
        tick_seconds,
        gcs_config=gcs_cfg,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
