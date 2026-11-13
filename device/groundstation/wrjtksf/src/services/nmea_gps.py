"""NMEA GNSS 解析与串口读取（独立实现，用于地面站位置）。"""
from __future__ import annotations

from typing import Optional, Tuple


def convert_ddm_to_decimal(coord_str: str, direction: str) -> Optional[float]:
    """度分格式 -> 十进制度。"""
    if not coord_str or not direction:
        return None
    try:
        dot_idx = coord_str.find(".")
        if dot_idx < 2:
            return None
        deg = int(coord_str[: dot_idx - 2])
        minutes = float(coord_str[dot_idx - 2 :])
        decimal = deg + minutes / 60.0
        if direction in ("S", "W"):
            decimal = -decimal
        return float(decimal)
    except Exception:
        return None


def parse_gga(data: str) -> Optional[dict]:
    parts = data.split(",")
    if len(parts) < 7:
        return None
    quality = parts[6]
    if quality == "0":
        return None
    lat = convert_ddm_to_decimal(parts[2], parts[3])
    lon = convert_ddm_to_decimal(parts[4], parts[5])
    if lat is None or lon is None:
        return None
    return {"latitude": lat, "longitude": lon, "quality": quality, "type": "GGA"}


def parse_rmc(data: str) -> Optional[dict]:
    parts = data.split(",")
    if len(parts) < 10:
        return None
    if parts[2] != "A":
        return None
    lat = convert_ddm_to_decimal(parts[3], parts[4])
    lon = convert_ddm_to_decimal(parts[5], parts[6])
    if lat is None or lon is None:
        return None
    return {"latitude": lat, "longitude": lon, "type": "RMC"}


def read_gps_fix_sync(port: str, baud: int = 115200, *, max_lines: int = 80, timeout: float = 1.0) -> Tuple[Optional[float], Optional[float]]:
    """
    打开串口读取若干行 NMEA，返回首个有效 GGA/RMC 的经纬度。
    失败返回 (None, None)。
    """
    try:
        import serial
    except ImportError:
        return None, None

    try:
        with serial.Serial(port, baud, timeout=timeout) as ser:
            for _ in range(max_lines):
                line = ser.readline().decode("ascii", errors="ignore").strip()
                if not line.startswith("$"):
                    continue
                if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
                    p = parse_gga(line)
                    if p:
                        return p["latitude"], p["longitude"]
                if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                    p = parse_rmc(line)
                    if p:
                        return p["latitude"], p["longitude"]
    except Exception:
        return None, None
    return None, None
