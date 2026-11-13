"""几何与坐标工具: 经纬度 <-> 本地 ENU 平面, 以及碰撞检测等基础原语。"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

# 地球常数(本地 ENU 平面近似, 适用于起降场周边数公里范围, 误差可忽略)
M_PER_DEG_LAT = 111320.0


def meters_per_deg_lon(lat_deg: float) -> float:
    """给定纬度下每经度对应的米数。"""
    return M_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def make_converter(ref_lat: float, ref_lon: float, ref_alt: float):
    """构造经纬度<->ENU 双向转换器。

    ENU: x 东向, y 北向, z 相对参考点标高(米, 向上为正)。
    """
    mpdl = meters_per_deg_lon(ref_lat)

    def to_enu(lat: float, lon: float, alt: float) -> Tuple[float, float, float]:
        x = (lon - ref_lon) * mpdl
        y = (lat - ref_lat) * M_PER_DEG_LAT
        z = alt - ref_alt
        return x, y, z

    def to_latlon(x: float, y: float, z: float) -> Tuple[float, float, float]:
        lon = ref_lon + x / mpdl
        lat = ref_lat + y / M_PER_DEG_LAT
        alt = ref_alt + z
        return lat, lon, alt

    return to_enu, to_latlon


def dist2d(p: Tuple[float, float], q: Tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def dist3d(p: Tuple[float, float, float], q: Tuple[float, float, float]) -> float:
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


def point_in_polygon(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> bool:
    """射线法判断点是否在多边形内(含边界)。"""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_cylinder_collides(p: Tuple[float, float, float],
                            cx: float, cy: float,
                            base_agl: float, top_agl: float,
                            radius: float) -> bool:
    """判断点是否落入以 (cx, cy) 为心的垂直圆柱(含保护区膨胀)。"""
    if math.hypot(p[0] - cx, p[1] - cy) > radius:
        return False
    return base_agl <= p[2] <= top_agl


def segment_free(p: Tuple[float, float, float],
                 q: Tuple[float, float, float],
                 obstacles: Sequence,
                 clearance: float = 0.0,
                 step: float = 10.0) -> bool:
    """判断线段 p->q 是否无碰撞(用于 A*/RRT*/平滑/仿真)。

    对每个障碍物圆柱: 若线段与圆柱的水平膨胀区相交, 且高度区间重叠, 则碰撞。
    采用等间距采样 + 膨胀半径判定, 步长 10m 对演示规模足够。
    """
    d = dist3d(p, q)
    if d < 1e-9:
        return True
    n = max(1, int(d / step))
    for i in range(n + 1):
        t = i / n
        x = p[0] + (q[0] - p[0]) * t
        y = p[1] + (q[1] - p[1]) * t
        z = p[2] + (q[2] - p[2]) * t
        for o in obstacles:
            r = o.inflated_radius + clearance
            if math.hypot(x - o.x, y - o.y) <= r and (o.base_agl - clearance) <= z <= (o.top_agl + clearance):
                return False
    return True


def poly_distance(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> float:
    """点到多边形边界的近似最近距离(米); 点在内部时返回 0。"""
    if point_in_polygon(px, py, poly):
        return 0.0
    n = len(poly)
    best = float("inf")
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        best = min(best, _point_segment_dist(px, py, a, b))
    return best


def _point_segment_dist(px, py, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def turn_radius_from_points(p0: Tuple[float, float], p1: Tuple[float, float],
                            p2: Tuple[float, float]) -> float:
    """由三个相邻航路点估算转弯半径(三点定圆); 共线时返回 inf。"""
    x0, y0 = p0[0], p0[1]
    x1, y1 = p1[0], p1[1]
    x2, y2 = p2[0], p2[1]
    d = 2 * (x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1))
    if abs(d) < 1e-9:
        return float("inf")
    ux = ((x0 ** 2 + y0 ** 2) * (y1 - y2) + (x1 ** 2 + y1 ** 2) * (y2 - y0)
          + (x2 ** 2 + y2 ** 2) * (y0 - y1)) / d
    uy = ((x0 ** 2 + y0 ** 2) * (x2 - x1) + (x1 ** 2 + y1 ** 2) * (x0 - x2)
          + (x2 ** 2 + y2 ** 2) * (x1 - x0)) / d
    r = math.hypot(x0 - ux, y0 - uy)
    return r
