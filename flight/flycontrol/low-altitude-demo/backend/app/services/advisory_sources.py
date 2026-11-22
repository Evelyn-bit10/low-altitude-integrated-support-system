"""Validate server-side source policy and observation metadata."""
import math
import os
from datetime import datetime

REQUIRED_SOURCES = ("meteo", "obstacles", "airspace")


def assess_sources(metadata, now):
    metadata = metadata if isinstance(metadata, dict) else {}
    sources = {}
    for name in REQUIRED_SOURCES:
        entry = metadata.get(name)
        entry = entry if isinstance(entry, dict) else {}
        source = entry.get("source")
        expected = os.getenv("ADVISORY_%s_SOURCE" % name.upper(), "").strip()
        try:
            max_age = float(os.getenv("ADVISORY_%s_MAX_AGE_SECONDS" % name.upper(), ""))
        except ValueError:
            max_age = 0
        observed = None
        try:
            parsed = datetime.fromisoformat(entry.get("observed_at", ""))
            if parsed.utcoffset() is not None:
                observed = parsed
        except (ValueError, TypeError, OverflowError):
            pass
        status = "unknown"
        if expected and isinstance(source, str) and source.strip() and source != expected:
            status = "conflict"
        elif (expected and source == expected and entry.get("trusted") is True
              and observed and math.isfinite(max_age) and max_age > 0):
            age = (now - observed).total_seconds()
            if age < 0:
                status = "future"
            else:
                status = "stale" if age > max_age else "fresh"
        sources[name] = {
            "source": source if isinstance(source, str) else None,
            "observed_at": observed.isoformat() if observed else None,
            "status": status,
        }
    statuses = {entry["status"] for entry in sources.values()}
    freshness = next(status for status in ("conflict", "future", "stale", "unknown", "fresh") if status in statuses)
    return freshness, sources
