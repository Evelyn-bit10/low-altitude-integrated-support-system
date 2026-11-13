from src.domain.models import Drone, Slot, Vec2
from src.engine.dock_scheduler import DockScheduler


def test_assign_nearest_available_slot():
    scheduler = DockScheduler()
    drone = Drone(drone_id="D1", position=Vec2(-100, 0), altitude=10, speed=10)
    slots = [
        Slot(slot_id="S1", center=Vec2(0, 0)),
        Slot(slot_id="S2", center=Vec2(100, 0)),
    ]
    assigned = scheduler.assign_slot(drone, slots, now=0.0)
    assert assigned is not None
    assert assigned.slot_id == "S1"


def test_assign_none_when_all_occupied():
    scheduler = DockScheduler()
    drone = Drone(drone_id="D1", position=Vec2(-100, 0), altitude=10, speed=10)
    slots = [
        Slot(slot_id="S1", center=Vec2(0, 0), occupied_by="X", occupied_until=100),
        Slot(slot_id="S2", center=Vec2(100, 0), occupied_by="Y", occupied_until=100),
    ]
    assigned = scheduler.assign_slot(drone, slots, now=0.0)
    assert assigned is None
