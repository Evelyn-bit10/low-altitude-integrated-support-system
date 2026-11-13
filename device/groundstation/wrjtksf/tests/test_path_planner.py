from src.domain.models import Vec2
from src.engine.path_planner import PathPlanner


def test_plan_inbound_ends_at_slot_and_altitude_zero():
    planner = PathPlanner(
        inbound_entry=Vec2(-170, 30),
        outbound_exit=Vec2(190, -30),
        far_exit=Vec2(-240, -200),
        cruise_altitude=12.0,
    )
    route = planner.plan_inbound(start=Vec2(-140, 20), slot_center=Vec2(0, 40))
    assert len(route.waypoints) >= 3
    assert route.waypoints[-1].position == Vec2(0, 40)
    assert route.waypoints[-1].altitude == 0.0


def test_plan_outbound_rises_from_zero():
    planner = PathPlanner(
        inbound_entry=Vec2(-170, 30),
        outbound_exit=Vec2(190, -30),
        far_exit=Vec2(300, -200),
        cruise_altitude=12.0,
    )
    route = planner.plan_outbound(slot_center=Vec2(0, 40))
    assert len(route.waypoints) >= 3
    assert route.waypoints[0].altitude == 0.0
    assert route.waypoints[-1].altitude == 12.0
    assert route.waypoints[-1].position == Vec2(300, -200)
