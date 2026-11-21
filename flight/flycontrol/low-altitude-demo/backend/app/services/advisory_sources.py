"""Validate metadata attached to the same advisory snapshot by a server adapter."""
import math
import os
from datetime import datetime

REQUIRED_SOURCES = ("meteo", "obstacles", "airspace")


def assess_sources(metadata, now):
    metadata = metadata if isinstance(metadata, dict) else {}
    try:
        max_age = float(os.getenv("ADVISORY_MAX_AGE_SECONDS", ""))
    except ValueError:
        max_age = 0
    sources = {}
    for name in REQUIRED_SOURCES:
        entry = metadata.get(name)
        entry = entry if isinstance(entry, dict) else {}
        source = entry.get("source")
        observed = None
        try:
            parsed = datetime.fromisoformat(entry.get("observed_at", ""))
            if parsed.utcoffset() is not None:
                observed = parsed
        except (ValueError, TypeError, OverflowError):
            pass
        status = "unknown"
        if isinstance(source, str) and source.strip() and entry.get("trusted") is True and observed:
            age = (now - observed).total_seconds()
            if age < 0:
                status = "future"
            elif math.isfinite(max_age) and max_age > 0:
                status = "stale" if age > max_age else "fresh"
        sources[name] = {
            "source": source if isinstance(source, str) else None,
            "observed_at": observed.isoformat() if observed else None,
            "status": status,
        }
    statuses = {entry["status"] for entry in sources.values()}
    freshness = next(status for status in ("future", "stale", "unknown", "fresh") if status in statuses)
    return freshness, sources
