"""一次性天气连通性检测（开发用）：python scripts/_weather_smoke.py"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.services.weather_service import fetch_current_weather


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / "config" / "demo_config.yaml").read_text(encoding="utf-8"))
    key = str((cfg.get("gcs") or {}).get("weather_api_key") or "").strip()
    if not key:
        print("config/gcs.weather_api_key 为空")
        return
    try:
        d = fetch_current_weather(key, 39.9042, 116.4074)
        print("成功:", d.get("condition"), d.get("temperature"), "°C @", d.get("location_name"))
    except Exception as e:
        print("失败:", e)


if __name__ == "__main__":
    main()
