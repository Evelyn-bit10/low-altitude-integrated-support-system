"""天气查询（WeatherAPI.com），使用标准库 urllib，无 aiohttp 依赖。"""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from typing import Any, Dict, Optional


def parse_weather_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """解析 WeatherAPI current.json 响应为 UI 使用的扁平字典。"""
    try:
        current = data.get("current", {}) or {}
        location = data.get("location", {}) or {}
        air_quality = current.get("air_quality", {}) or {}
        return {
            "temperature": current.get("temp_c"),
            "humidity": current.get("humidity"),
            "visibility": current.get("vis_km"),
            "precipitation": current.get("precip_mm"),
            "wind_speed": current.get("wind_kph"),
            "wind_dir": current.get("wind_dir"),
            "pressure": current.get("pressure_mb"),
            "cloud": current.get("cloud"),
            "feelslike": current.get("feelslike_c"),
            "uv": current.get("uv"),
            "gust": current.get("gust_kph"),
            "condition": (current.get("condition") or {}).get("text", "未知"),
            "condition_code": (current.get("condition") or {}).get("code"),
            "condition_icon": (current.get("condition") or {}).get("icon"),
            "air_quality": {
                "co": air_quality.get("co"),
                "no2": air_quality.get("no2"),
                "o3": air_quality.get("o3"),
                "so2": air_quality.get("so2"),
                "pm2_5": air_quality.get("pm2_5"),
                "pm10": air_quality.get("pm10"),
                "us_epa_index": air_quality.get("us-epa-index"),
                "gb_defra_index": air_quality.get("gb-defra-index"),
            },
            "last_updated": current.get("last_updated"),
            "location_name": f"{location.get('name', '未知')}, {location.get('country', '未知')}",
            "localtime": location.get("localtime"),
        }
    except Exception:
        return {
            "temperature": None,
            "humidity": None,
            "visibility": None,
            "precipitation": None,
            "condition": "数据解析失败",
            "location_name": "未知位置",
            "air_quality": {},
        }


def _decode_http_body(raw: bytes, headers) -> str:
    """按 Content-Encoding 解压，再按 UTF-8 解码（避免 gzip 二进制被误当 UTF-8）。"""
    enc = (headers.get("Content-Encoding") or "").lower().strip()
    data = raw
    if enc == "gzip" or (len(raw) >= 2 and raw[:2] == b"\x1f\x8b"):
        data = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            data = zlib.decompress(raw, -zlib.MAX_WBITS)
    return data.decode("utf-8", errors="replace")


def fetch_current_weather(api_key: str, lat: float, lon: float) -> Dict[str, Any]:
    """同步 HTTP 请求当前天气。"""
    if not api_key or not api_key.strip():
        raise ValueError("未配置天气 API Key（config/gcs.weather_api_key 或环境变量 WEATHERAPI_KEY）")

    params = urllib.parse.urlencode(
        {
            "key": api_key.strip(),
            "q": f"{lat},{lon}",
            "aqi": "yes",
            "lang": "zh",
        }
    )
    url = f"https://api.weatherapi.com/v1/current.json?{params}"
    # 不显式要 gzip：部分环境下 urllib 不会自动解压，会导致 JSON 解析失败。
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DockingDemo/1.0 (urllib)"},
        method="GET",
    )
    raw: bytes = b""
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            text = _decode_http_body(raw, resp.headers)
            data = json.loads(text)
    except json.JSONDecodeError as e:
        preview = raw[:120] if isinstance(raw, (bytes, bytearray)) else str(raw)[:120]
        raise RuntimeError(f"天气响应不是合法 JSON: {e}; 开头字节/字符: {preview!r}") from e
    except urllib.error.HTTPError as e:
        try:
            err_raw = e.read()
            err_text = _decode_http_body(err_raw, getattr(e, "headers", {}) or {})
        except Exception:
            err_text = str(e)
        raise RuntimeError(f"WeatherAPI HTTP {e.code}: {err_text[:500]}") from e
    except Exception as e:
        raise RuntimeError(f"天气请求失败: {e}") from e

    err = data.get("error")
    if isinstance(err, dict):
        code = err.get("code", "?")
        msg = err.get("message", str(err))
        raise RuntimeError(f"WeatherAPI 错误 [{code}]: {msg}")
    if err and not data.get("current"):
        raise RuntimeError(f"WeatherAPI 异常响应: {repr(data)[:500]}")

    parsed = parse_weather_payload(data)
    parsed["timestamp"] = datetime.now().timestamp()
    return parsed


class WeatherCache:
    """简单内存缓存，避免过于频繁请求。"""

    def __init__(self, update_interval_seconds: float = 300.0) -> None:
        self.update_interval_seconds = update_interval_seconds
        self.last_data: Optional[Dict[str, Any]] = None
        self.last_update: Optional[datetime] = None

    def get(
        self,
        api_key: str,
        lat: float,
        lon: float,
        *,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        now = datetime.now()
        if (
            not force_refresh
            and self.last_data is not None
            and self.last_update is not None
            and (now - self.last_update).total_seconds() < self.update_interval_seconds
        ):
            return self.last_data
        data = fetch_current_weather(api_key, lat, lon)
        self.last_data = data
        self.last_update = now
        return data
