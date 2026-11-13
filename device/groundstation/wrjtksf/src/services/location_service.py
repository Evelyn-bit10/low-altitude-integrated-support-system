"""地面站位置：硬件 GNSS (NMEA) → Windows 系统定位 → 由调用方使用配置默认。"""
from __future__ import annotations

import asyncio
import platform
from typing import Optional


def get_location_sync(
    gps_port: str | None = None,
    gps_baud: int = 115200,
) -> tuple[Optional[float], Optional[float]]:
    """
    同步获取位置：
    1) 若提供 gps_port，则从串口读 NMEA（GGA/RMC）；
    2) Windows 下再尝试 WinRT；
    3) 均失败返回 (None, None)，由上层使用 yaml 默认坐标。
    """
    port = (gps_port or "").strip()
    if port:
        from src.services.nmea_gps import read_gps_fix_sync

        fix = read_gps_fix_sync(port, int(gps_baud))
        if fix[0] is not None and fix[1] is not None:
            return float(fix[0]), float(fix[1])

    if platform.system() == "Windows":
        return _get_windows_location_sync()
    return None, None


def _get_windows_location_sync() -> tuple[Optional[float], Optional[float]]:
    try:
        from winrt.windows.devices.geolocation import Geolocator  # type: ignore[import-not-found]
    except Exception:
        return None, None

    async def _run() -> tuple[Optional[float], Optional[float]]:
        try:
            locator = Geolocator()
            pos = await locator.get_geoposition_async()
            return pos.coordinate.latitude, pos.coordinate.longitude
        except Exception:
            return None, None

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        lat, lon = loop.run_until_complete(_run())
        loop.close()
        return lat, lon
    except Exception:
        return None, None
