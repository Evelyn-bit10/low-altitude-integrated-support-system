from __future__ import annotations

from src.domain.models import Drone, Route, Vec2


def _segment_closest(p: Vec2, a: Vec2, b: Vec2) -> tuple[float, Vec2, float]:
    """线段上最近点：返回 (t∈[0,1], 最近点, 距离)。"""
    abx = b.x - a.x
    aby = b.y - a.y
    apx = p.x - a.x
    apy = p.y - a.y
    denom = abx * abx + aby * aby
    if denom < 1e-18:
        d = p.distance_to(a)
        return 0.0, Vec2(a.x, a.y), d
    t = (apx * abx + apy * aby) / denom
    t = max(0.0, min(1.0, t))
    cx = a.x + t * abx
    cy = a.y + t * aby
    closest = Vec2(cx, cy)
    return t, closest, p.distance_to(closest)


def _point_to_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    _, _, d = _segment_closest(p, a, b)
    return d


class DeviationMonitor:
    def __init__(self, distance_threshold: float, duration_threshold: float) -> None:
        self.distance_threshold = distance_threshold
        self.duration_threshold = duration_threshold

    def min_route_distance(self, position: Vec2, route: Route) -> float:
        waypoints = route.waypoints
        if len(waypoints) < 2:
            return 0.0
        return min(
            _point_to_segment_distance(position, waypoints[i].position, waypoints[i + 1].position)
            for i in range(len(waypoints) - 1)
        )

    def closest_on_route(self, position: Vec2, route: Route) -> tuple[Vec2, int, float]:
        """规划折线上距离 position 最近的点：返回 (最近点, 线段起点下标 i, 该线段上参数 t)。"""
        wps = route.waypoints
        if len(wps) < 2:
            return Vec2(position.x, position.y), 0, 0.0
        best_d = 1e30
        best_c = wps[0].position
        best_i = 0
        best_t = 0.0
        for i in range(len(wps) - 1):
            t, c, d = _segment_closest(position, wps[i].position, wps[i + 1].position)
            if d < best_d:
                best_d = d
                best_c = c
                best_i = i
                best_t = t
        return best_c, best_i, best_t

    def escape_unit_from_route(self, position: Vec2, route: Route) -> Vec2:
        """单位方向：沿此方向移动会增大到路径的横向距离（在路径上时取线段法向）。"""
        closest, seg_i, _t = self.closest_on_route(position, route)
        wps = route.waypoints
        dx = position.x - closest.x
        dy = position.y - closest.y
        mag = (dx * dx + dy * dy) ** 0.5
        if mag > 1.0:
            return Vec2(dx / mag, dy / mag)
        a = wps[seg_i].position
        b = wps[seg_i + 1].position
        abx = b.x - a.x
        aby = b.y - a.y
        abm = (abx * abx + aby * aby) ** 0.5
        if abm < 1e-9:
            return Vec2(0.0, 1.0)
        return Vec2(-aby / abm, abx / abm)

    def check_deviation(self, drone: Drone, dt: float) -> bool:
        if not drone.planned_route:
            drone.deviation_timer = 0.0
            return False

        d = self.min_route_distance(drone.position, drone.planned_route)
        if d > self.distance_threshold:
            drone.deviation_timer += dt
            return drone.deviation_timer >= self.duration_threshold

        drone.deviation_timer = 0.0
        return False
