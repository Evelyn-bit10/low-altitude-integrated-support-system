"""A* 路径规划器 + Catmull-Rom 样条平滑 + 最小转弯半径约束。"""
from __future__ import annotations

import heapq
import math
from typing import Dict, Iterable, List, Tuple

from engine.sim_models import NoFlyZone, Obstacle, Route, Vec2, Waypoint


class PathPlanner:
    def __init__(
        self,
        inbound_entry: Vec2,
        outbound_exit: Vec2,
        far_exit: Vec2,
        cruise_altitude: float,
        obstacles: List[Obstacle] | None = None,
        no_fly_zones: List[NoFlyZone] | None = None,
        grid_step: float = 10.0,
        spline_samples_per_segment: int = 8,
        min_turn_radius: float = 18.0,
    ) -> None:
        self.inbound_entry = inbound_entry
        self.outbound_exit = outbound_exit
        self.far_exit = far_exit
        self.cruise_altitude = cruise_altitude
        self.obstacles = obstacles or []
        self.no_fly_zones = no_fly_zones or []
        self.grid_step = grid_step
        self.spline_samples_per_segment = max(3, spline_samples_per_segment)
        self.min_turn_radius = max(1.0, min_turn_radius)

    def _to_grid(self, p: Vec2) -> tuple[int, int]:
        return (int(round(p.x / self.grid_step)), int(round(p.y / self.grid_step)))

    def _from_grid(self, node: tuple[int, int]) -> Vec2:
        return Vec2(node[0] * self.grid_step, node[1] * self.grid_step)

    def _is_blocked(self, p: Vec2) -> bool:
        for obs in self.obstacles:
            if p.distance_to(obs.center) <= (obs.radius + 6.0):
                return True
        for nfz in self.no_fly_zones:
            if nfz.zone.contains(p):
                return True
        return False

    def _neighbors(self, n: tuple[int, int]) -> Iterable[tuple[int, int]]:
        x, y = n
        for dx, dy in (
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (-1, 1), (1, -1), (1, 1),
        ):
            yield (x + dx, y + dy)

    def _astar(self, start: Vec2, goal: Vec2) -> List[Vec2]:
        s = self._to_grid(start)
        g = self._to_grid(goal)

        points = [start, goal, self.inbound_entry, self.outbound_exit, self.far_exit] + \
                 [o.center for o in self.obstacles]
        min_x = min(p.x for p in points) - 80
        max_x = max(p.x for p in points) + 80
        min_y = min(p.y for p in points) - 80
        max_y = max(p.y for p in points) + 80
        x_min_g = int(min_x // self.grid_step)
        x_max_g = int(max_x // self.grid_step)
        y_min_g = int(min_y // self.grid_step)
        y_max_g = int(max_y // self.grid_step)

        open_heap: List[Tuple[float, tuple[int, int]]] = []
        heapq.heappush(open_heap, (0.0, s))
        came_from: Dict[tuple[int, int], tuple[int, int]] = {}
        g_score: Dict[tuple[int, int], float] = {s: 0.0}

        def h(node: tuple[int, int]) -> float:
            dx = node[0] - g[0]
            dy = node[1] - g[1]
            return (dx * dx + dy * dy) ** 0.5

        visited = set()
        while open_heap:
            _, current = heapq.heappop(open_heap)
            if current in visited:
                continue
            visited.add(current)
            if current == g:
                break

            for nb in self._neighbors(current):
                if not (x_min_g <= nb[0] <= x_max_g and y_min_g <= nb[1] <= y_max_g):
                    continue
                nb_world = self._from_grid(nb)
                if self._is_blocked(nb_world):
                    continue
                step = 1.414 if nb[0] != current[0] and nb[1] != current[1] else 1.0
                tentative = g_score[current] + step
                if tentative < g_score.get(nb, 1e18):
                    came_from[nb] = current
                    g_score[nb] = tentative
                    f = tentative + h(nb)
                    heapq.heappush(open_heap, (f, nb))

        if g not in came_from and s != g:
            return [start, goal]

        nodes = [g]
        while nodes[-1] != s:
            parent = came_from.get(nodes[-1])
            if parent is None:
                return [start, goal]
            nodes.append(parent)
        nodes.reverse()
        return [self._from_grid(n) for n in nodes]

    def _catmull_rom_cubic_spline(self, points: List[Vec2]) -> List[Vec2]:
        if len(points) < 3:
            return points
        pts = [points[0]] + points + [points[-1]]
        out: List[Vec2] = [points[0]]
        samples = self.spline_samples_per_segment
        for i in range(1, len(pts) - 2):
            p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
            for s in range(1, samples + 1):
                t_val = s / samples
                t2 = t_val * t_val
                t3 = t2 * t_val
                x = 0.5 * (
                    (2 * p1.x)
                    + (-p0.x + p2.x) * t_val
                    + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2
                    + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3
                )
                y = 0.5 * (
                    (2 * p1.y)
                    + (-p0.y + p2.y) * t_val
                    + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2
                    + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3
                )
                out.append(Vec2(x, y))
        out[0] = points[0]
        out[-1] = points[-1]
        return out

    def _circum_radius(self, a: Vec2, b: Vec2, c: Vec2) -> float:
        ab = a.distance_to(b)
        bc = b.distance_to(c)
        ca = c.distance_to(a)
        s_val = (ab + bc + ca) / 2.0
        area_sq = max(0.0, s_val * (s_val - ab) * (s_val - bc) * (s_val - ca))
        if area_sq <= 1e-9:
            return 1e9
        area = math.sqrt(area_sq)
        return (ab * bc * ca) / (4.0 * area)

    def _enforce_min_turn_radius(self, points: List[Vec2]) -> List[Vec2]:
        if len(points) < 3:
            return points
        out = [Vec2(p.x, p.y) for p in points]
        for _ in range(4):
            updated = False
            for i in range(1, len(out) - 1):
                r = self._circum_radius(out[i - 1], out[i], out[i + 1])
                if r < self.min_turn_radius:
                    mx = (out[i - 1].x + out[i + 1].x) * 0.5
                    my = (out[i - 1].y + out[i + 1].y) * 0.5
                    out[i] = Vec2(out[i].x * 0.45 + mx * 0.55, out[i].y * 0.45 + my * 0.55)
                    updated = True
            if not updated:
                break
        return out

    def _with_altitude(self, pts: List[Vec2], start_alt: float, end_alt: float, route_type: str) -> Route:
        if len(pts) == 1:
            return Route([Waypoint(pts[0], end_alt)], route_type=route_type)
        total = 0.0
        seg_lens = []
        for i in range(len(pts) - 1):
            d = pts[i].distance_to(pts[i + 1])
            seg_lens.append(d)
            total += d
        acc = 0.0
        waypoints: List[Waypoint] = []
        for i, p in enumerate(pts):
            if i > 0:
                acc += seg_lens[i - 1]
            t_val = 0.0 if total == 0 else acc / total
            alt = start_alt + (end_alt - start_alt) * t_val
            waypoints.append(Waypoint(p, alt))
        waypoints[-1].altitude = end_alt
        return Route(waypoints=waypoints, route_type=route_type)

    def plan_inbound(self, start: Vec2, slot_center: Vec2) -> Route:
        p1 = self._astar(start, self.inbound_entry)
        p2 = self._astar(self.inbound_entry, slot_center)
        path = p1 + p2[1:] if len(p2) > 1 else p1
        smooth = self._catmull_rom_cubic_spline(path)
        smooth = self._enforce_min_turn_radius(smooth)
        return self._with_altitude(smooth, self.cruise_altitude, 0.0, "inbound")

    def plan_outbound(self, slot_center: Vec2) -> Route:
        p1 = self._astar(slot_center, self.outbound_exit)
        p2 = self._astar(self.outbound_exit, self.far_exit)
        path = p1 + p2[1:] if len(p2) > 1 else p1
        smooth = self._catmull_rom_cubic_spline(path)
        smooth = self._enforce_min_turn_radius(smooth)
        return self._with_altitude(smooth, 0.0, self.cruise_altitude, "outbound")
