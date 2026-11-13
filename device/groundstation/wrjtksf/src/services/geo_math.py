"""WGS84 与本地平面米制坐标（以地面站为原点）的近似换算。"""
from __future__ import annotations

import math


def world_meters_to_wgs84(base_lat: float, base_lon: float, x_m: float, y_m: float) -> tuple[float, float]:
    """
    将相对地面站的东向 x（米）、北向 y（米）换算为 WGS84 经纬度。
    适用于演示尺度（数公里内误差可接受）。
    """
    lat = base_lat + y_m / 111_111.0
    cos_lat = math.cos(math.radians(base_lat))
    cos_lat = max(cos_lat, 0.01)
    lon = base_lon + x_m / (111_111.0 * cos_lat)
    return lat, lon


def wgs84_to_world_meters(base_lat: float, base_lon: float, lat: float, lon: float) -> tuple[float, float]:
    """WGS84 相对 base 的东向、北向米偏移（逆运算）。"""
    dy = (lat - base_lat) * 111_111.0
    cos_lat = math.cos(math.radians(base_lat))
    cos_lat = max(cos_lat, 0.01)
    dx = (lon - base_lon) * 111_111.0 * cos_lat
    return dx, dy
