"""坐标桥接模块 — 将仿真 Vec2(x,y) 米制坐标转换为 Leaflet 可用的 GCJ02 经纬度。

仿真引擎内部使用东向 x / 北向 y 米制坐标，引擎 Vec2(0,0) 原点对应
地面站 GCS 的 WGS84 经纬度 (gcs_lat, gcs_lon)。
本模块桥接：Vec2(x_m, y_m) → WGS84 → GCJ02（用于 Leaflet 地图显示）。
"""
from __future__ import annotations

from typing import List, Tuple

from engine.geo_math import world_meters_to_wgs84, wgs84_to_world_meters
from engine.sim_models import Vec2, Route
from utils.coordinates import wgs84_to_gcj02


class CoordBridge:
    """仿真坐标 ↔ 地图经纬度 双向转换。"""

    def __init__(self, gcs_lat: float = 29.52, gcs_lon: float = 106.56):
        self.gcs_lat = gcs_lat
        self.gcs_lon = gcs_lon

    def vec2_to_gcj02(self, pos: Vec2) -> Tuple[float, float]:
        """Vec2(x_m, y_m) → GCJ02 (lat, lng)，供 Leaflet 地图使用。"""
        wgs_lat, wgs_lon = world_meters_to_wgs84(self.gcs_lat, self.gcs_lon, pos.x, pos.y)
        return wgs84_to_gcj02(wgs_lat, wgs_lon)

    def vec2_to_wgs84(self, pos: Vec2) -> Tuple[float, float]:
        """Vec2(x_m, y_m) → WGS84 (lat, lng)，供遥测数据使用。"""
        return world_meters_to_wgs84(self.gcs_lat, self.gcs_lon, pos.x, pos.y)

    def gcj02_to_vec2(self, gcj_lat: float, gcj_lng: float) -> Vec2:
        """GCJ02 → Vec2(x_m, y_m)（简化：直接将 GCJ02 视为 WGS84 近似逆算）。"""
        dx, dy = wgs84_to_world_meters(self.gcs_lat, self.gcs_lon, gcj_lat, gcj_lng)
        return Vec2(dx, dy)

    def route_to_gcj02_polyline(self, route: Route) -> List[Tuple[float, float]]:
        """将 Route 所有航点转为 GCJ02 坐标列表，用于 Leaflet polyline。"""
        return [self.vec2_to_gcj02(wp.position) for wp in route.waypoints]

    def vec2_list_to_gcj02(self, points: List[Vec2]) -> List[Tuple[float, float]]:
        return [self.vec2_to_gcj02(p) for p in points]
