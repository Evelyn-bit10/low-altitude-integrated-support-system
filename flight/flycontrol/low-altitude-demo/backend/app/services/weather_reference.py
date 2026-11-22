"""District-level weather reference; never used as operational meteo."""
from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

_CONFIG_FILE = Path(__file__).resolve().parents[2] / ".env.amap"
_ENDPOINT = "https://restapi.amap.com/v3/weather/weatherInfo"
_SHANGHAI = timezone(timedelta(hours=8))
_MAX_AGE = timedelta(hours=3)


def _key() -> str:
    value = os.getenv("AMAP_API_KEY", "").strip()
    if value:
        return value
    try:
        for line in _CONFIG_FILE.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "AMAP_API_KEY":
                return value.strip().strip("\"'")
    except (OSError, UnicodeError):
        pass
    return ""


def _short_text(value, limit=80):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid field")
    return value


def _parse(data, adcode, now, location="重庆邮电大学（重庆市南岸区）"):
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        raise ValueError("provider rejected request")
    lives = data.get("lives")
    if not isinstance(lives, list) or len(lives) != 1 or not isinstance(lives[0], dict):
        raise ValueError("invalid weather response")
    row = lives[0]
    if row.get("adcode") != adcode:
        raise ValueError("wrong district")
    published = datetime.strptime(row["reporttime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SHANGHAI)
    if published > now.astimezone(_SHANGHAI):
        raise ValueError("future publication time")
    return {
        "source": "高德天气", "scope": "行政区天气参考，非现场观测",
        "location": location, "adcode": adcode,
        "weather": _short_text(row.get("weather")),
        "temperature_c": _short_text(row.get("temperature")),
        "wind_direction": _short_text(row.get("winddirection")),
        "wind_power_level": _short_text(row.get("windpower")),
        "humidity_percent": _short_text(row.get("humidity")),
        "published_at": published.isoformat(), "retrieved_at": now.isoformat(),
        "limitations": ["区域天气不是起降点实测，不含完整的航空气象数据，不可用于运行限制判定。"],
    }


def _request(endpoint, params):
    with urlopen(endpoint + "?" + urlencode(params), timeout=8) as response:
        return json.loads(response.read(65537))


def locate_weather(latitude, longitude):
    key = _key()
    if not key:
        return {"status": "unavailable", "reason": "not_configured", "data": None}
    try:
        coords = _request("https://restapi.amap.com/v3/assistant/coordinate/convert", {
            "key": key, "locations": f"{longitude:.6f},{latitude:.6f}", "coordsys": "gps"})
        if str(coords.get("status")) != "1":
            raise ValueError("coordinate conversion failed")
        converted = coords.get("locations", "")
        if not re.fullmatch(r"-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?", converted):
            raise ValueError("invalid coordinates")
        address = _request("https://restapi.amap.com/v3/geocode/regeo", {
            "key": key, "location": converted, "extensions": "base"})
        if str(address.get("status")) != "1":
            raise ValueError("reverse geocoding failed")
        component = address["regeocode"]["addressComponent"]
        adcode = component["adcode"]
        if not isinstance(adcode, str) or not re.fullmatch(r"\d{6}", adcode):
            raise ValueError("invalid district")
        location = " ".join(_short_text(component.get(name) or "") for name in ("province", "city", "district"))
        data = _request(_ENDPOINT, {"key": key, "city": adcode, "extensions": "base", "output": "JSON"})
        record = _parse(data, adcode, datetime.now(timezone.utc), location.strip())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(record["published_at"])
        return {"status": "current" if timedelta(0) <= age <= _MAX_AGE else "stale", "reason": None, "data": record}
    except Exception:
        return {"status": "unavailable", "reason": "fetch_failed", "data": None}


class WeatherReference:
    def __init__(self, adcode="500108"):
        if not re.fullmatch(r"\d{6}", adcode):
            raise ValueError("invalid adcode")
        self.adcode = adcode
        self._lock = threading.Lock()
        self._record = None
        self._error = "not_fetched"

    def refresh(self):
        key = _key()
        if not key:
            with self._lock:
                self._error = "not_configured"
            return
        params = urlencode({"key": key, "city": self.adcode, "extensions": "base", "output": "JSON"})
        try:
            with urlopen(_ENDPOINT + "?" + params, timeout=8) as response:
                data = json.loads(response.read(65537))
            record = _parse(data, self.adcode, datetime.now(timezone.utc))
        except Exception:
            with self._lock:
                self._error = "fetch_failed"
            return
        with self._lock:
            self._record = record
            self._error = None

    def snapshot(self):
        with self._lock:
            record, error = deepcopy(self._record), self._error
        if record is None:
            return {"status": "unavailable", "reason": error, "data": None}
        now = datetime.now(timezone.utc)
        published = datetime.fromisoformat(record["published_at"])
        age = now - published
        status = "current" if timedelta(0) <= age <= _MAX_AGE else "stale"
        return {"status": status, "reason": error, "data": record}
