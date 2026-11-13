from src.domain.models import RectangleZone, Slot, Vec2
from src.engine.deviation_monitor import DeviationMonitor
from src.engine.dock_scheduler import DockScheduler
from src.engine.path_planner import PathPlanner
from src.engine.simulation_engine import SimulationEngine
from src.services.alert_service import AlertService


def _build_engine(max_inbound: int, dispatch_interval: float) -> SimulationEngine:
    waiting = RectangleZone(-220, -160, -120, 160)
    pad = RectangleZone(-40, -80, 120, 80)
    slots = [
        Slot("S1", Vec2(0, 40)),
        Slot("S2", Vec2(0, -40)),
        Slot("S3", Vec2(80, 40)),
        Slot("S4", Vec2(80, -40)),
    ]
    planner = PathPlanner(Vec2(-60, 0), Vec2(-80, 0), Vec2(-240, -200), 12.0)
    scheduler = DockScheduler()
    deviation = DeviationMonitor(9999.0, 9999.0)
    alert = AlertService(cooldown_seconds=1.0)
    engine = SimulationEngine(
        waiting_zone=waiting,
        pad_zone=pad,
        slots=slots,
        planner=planner,
        scheduler=scheduler,
        deviation_monitor=deviation,
        alert_service=alert,
        cruise_altitude=12.0,
        dock_dwell_seconds=5.0,
        max_concurrent_inbound=max_inbound,
        inbound_dispatch_interval_seconds=dispatch_interval,
    )
    engine.create_random_drones(6, 50.0)
    return engine


def test_inbound_concurrency_limit():
    engine = _build_engine(max_inbound=1, dispatch_interval=0.0)
    for _ in range(70):
        engine.step(0.1)
        inbound_count = sum(1 for d in engine.drones if d.status.value == "inbound")
        assert inbound_count <= 1


def test_dispatch_interval_staggers_assignments():
    engine = _build_engine(max_inbound=4, dispatch_interval=0.6)
    assignment_times = []
    seen = set()
    for _ in range(140):
        engine.step(0.1)
        for d in engine.drones:
            if d.status.value == "inbound" and d.drone_id not in seen:
                seen.add(d.drone_id)
                assignment_times.append(engine.now)
        if len(assignment_times) >= 3:
            break

    assert len(assignment_times) >= 2
    deltas = [assignment_times[i + 1] - assignment_times[i] for i in range(len(assignment_times) - 1)]
    assert all(delta >= 0.5 for delta in deltas)


def test_inbound_outbound_do_not_overlap():
    engine = _build_engine(max_inbound=2, dispatch_interval=0.0)
    for _ in range(500):
        engine.step(0.1)
        inbound_count = sum(1 for d in engine.drones if d.status.value == "inbound")
        outbound_count = sum(1 for d in engine.drones if d.status.value == "outbound")
        assert not (inbound_count > 0 and outbound_count > 0)
