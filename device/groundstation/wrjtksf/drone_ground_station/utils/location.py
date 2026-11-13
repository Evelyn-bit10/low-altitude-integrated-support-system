# utils/location.py
"""Location utilities - WinRT only on Windows, safe skip on Linux"""

import asyncio
import io
import platform# 在 Pi 上，用 scp 从你的 Windows 电脑传过去，或者直接编辑替换
# 目标路径: /home/pi/Desktop/drone_ground_station/utils/location.py
import sys

# Ensure stdout handles Unicode / special chars
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=sys.stdout.line_buffering,
        )
    except Exception:
        pass

# --- WinRT location (Windows only) ---
# DO NOT import winrt at module level -- it is Windows-only.
# All winrt access is guarded inside _init_winrt() with try/except + platform check.
_WINRT_CHECKED = False
_WINRT_AVAILABLE = False
_Geolocator = None


def _init_winrt():
    global _WINRT_CHECKED, _WINRT_AVAILABLE, _Geolocator
    if _WINRT_CHECKED:
        return
    _WINRT_CHECKED = True
    if platform.system() != "Windows":
        return
    try:
        from winrt.windows.devices.geolocation import Geolocator  # type: ignore
        _Geolocator = Geolocator
        _WINRT_AVAILABLE = True
    except Exception:
        pass


async def get_windows_location():
    _init_winrt()
    if not _WINRT_AVAILABLE or _Geolocator is None:
        return None, None
    try:
        locator = _Geolocator()
        pos = await locator.get_geoposition_async()
        return pos.coordinate.latitude, pos.coordinate.longitude
    except Exception as e:
        try:
            print(f"[WARN] Get location failed: {e}")
        except Exception:
            pass
        return None, None


def get_location_sync():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        lat, lng = loop.run_until_complete(get_windows_location())
        loop.close()
        return lat, lng
    except Exception as e:
        try:
            print(f"[WARN] Sync location failed: {e}")
        except Exception:
            pass
        return None, None