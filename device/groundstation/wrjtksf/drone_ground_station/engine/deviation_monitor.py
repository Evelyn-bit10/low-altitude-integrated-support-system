"""偏航监测器 — 判断无人机是否偏离计划航线。"""
from __future__ import annotations

from typing import Tuple

from engine.sim_models import Drone, Route, Vec2


class DeviationMonitor:
    def __init__(self, distance_threshold: float = 18.0, duration_threshold_seconds: float = 1.2):
        self.distance_threshold = distance_threshold
        self.duration_threshold_seconds = duration_threshold_seconds

    @staticmethod
    def min_route_distance(pos: Vec2, route: Route) -> float:
        if not route.waypoints:
            return float("inf")
        best = float("inf")
        for i in range(len(route.waypoints) - 1):
            a = route.waypoints[i].position
            b = route.waypoints[i + 1].position
            d = DeviationMonitor._point_segment_distance(pos, a, b)
            if d < best:
                best = d
        if best == float("inf") and len(route.waypoints) == 1:
            return pos.distance_to(route.waypoints[0].position)
        return best

    @staticmethod
    def _point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
        abx = b.x - a.x
        aby = b.y - a.y
        if abx == 0.0 and aby == 0.0:
            return p.distance_to(a)
        t = ((p.x - a.x) * abx + (p.y - a.y) * aby) / (abx * abx + aby * aby)
        if t < 0.0:
            return p.distance_to(a)
        if t > 1.0:
            return p.distance_to(b)
        px = a.x + t * abx
        py = a.y + t * aby
        return p.distance_to(Vec2(px, py))

    @staticmethod
    def closest_on_route(pos: Vec2, route: Route) -> Tuple[Vec2, int, float]:
        if not route.waypoints:
            return Vec2(pos.x, pos.y), 0, 0.0
        best_dist = float("inf")
        best_pt = Vec2(pos.x, pos.y)
        best_seg = 0
        best_t = 0.0
        for i in range(len(route.waypoints) - 1):
            a = route.waypoints[i].position
            b = route.waypoints[i + 1].position
            abx = b.x - a.x
            aby = b.y - a.y
            if abx == 0.0 and aby == 0.0:
                d = pos.distance_to(a)
                if d < best_dist:
                    best_dist = d
                    best_pt = Vec2(a.x, a.y)
                    best_seg = i
                    best_t = 0.0
                continue
            t = ((pos.x - a.x) * abx + (pos.y - a.y) * aby) / (abx * abx + aby * aby)
            t = max(0.0, min(1.0, t))
            cx = a.x + t * abx
            cy = a.y + t * aby
            d = pos.distance_to(Vec2(cx, cy))
            if d < best_dist:
                best_dist = d
                best_pt = Vec2(cx, cy)
                best_seg = i
                best_t = t
        return best_pt, best_seg, best_t

    @staticmethod
    def escape_unit_from_route(pos: Vec2, route: Route) -> Vec2:
        _, seg_i, t = DeviationMonitor.closest_on_route(pos, route)
        if len(route.waypoints) < 2:
            return Vec2(1.0, 0.0)
        a = route.waypoints[seg_i].position
        b = route.waypoints[seg_i + 1].position
        dx = b.x - a.x
        dy = b.y - a.y
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return Vec2(1.0, 0.0)
        nx = -dy / length
        ny = dx / length
        ex = pos.x - (a.x + (b.x - a.x) * t)
        ey = pos.y - (a.y + (b.y - a.y) * t)
        if ex * nx + ey * ny < 0:
            nx, ny = -nx, -ny
        return Vec2(nx, ny)

    def check_deviation(self, drone: Drone, dt: float) -> bool:
        if not drone.planned_route:
            return False
        dist = self.min_route_distance(drone.position, drone.planned_route)
        if dist > self.distance_threshold:
            drone.deviation_timer += dt
            if drone.deviation_timer > self.duration_threshold_seconds:
                return True
        else:
            drone.deviation_timer = 0.0
        return False
