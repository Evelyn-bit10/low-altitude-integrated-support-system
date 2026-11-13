"""机位与无人机匹配：尺寸、充电功率、几何重叠。"""
from __future__ import annotations

from typing import Iterable, Optional

from engine.sim_models import Drone, DroneSpec, Slot, Vec2


def default_battery_capacity_kwh(size_m: float) -> float:
    s = max(0.3, float(size_m))
    return max(0.06, 0.11 * (s**1.25))


def resolved_battery_kwh(spec: DroneSpec) -> float:
    if float(spec.battery_capacity_kwh) > 1e-9:
        return float(spec.battery_capacity_kwh)
    return default_battery_capacity_kwh(spec.size)


def effective_charge_kw(slot: Slot, spec: DroneSpec) -> float:
    req = max(0.01, float(spec.required_power))
    st = max(0.01, float(slot.station_charge_kw))
    cap = max(st, float(slot.station_charge_cap_kw))
    return max(0.01, min(st, cap, req))


def charge_time_seconds(soc_percent: float, battery_kwh: float, p_kw: float) -> float:
    soc = max(0.0, min(100.0, float(soc_percent)))
    kwh = max(1e-6, float(battery_kwh))
    need = (100.0 - soc) / 100.0 * kwh
    return (need / max(p_kw, 1e-6)) * 3600.0


def slot_accepts_drone(slot: Slot, drone: Drone, now: float) -> bool:
    if drone.spec is None:
        return True
    return float(drone.spec.size) <= float(slot.max_drone_size_m) + 1e-9


def slot_available_for_drone(slot: Slot, drone: Drone, now: float) -> bool:
    occ_ok = slot.occupied_by is None or slot.occupied_until <= now or slot.occupied_by == drone.drone_id
    return occ_ok and slot_accepts_drone(slot, drone, now)


def circles_overlap(c1: Vec2, r1: float, c2: Vec2, r2: float) -> bool:
    d = c1.distance_to(c2)
    return d < (float(r1) + float(r2)) - 1e-6


def candidate_conflicts_with_list(candidate: Slot, existing: Iterable[Slot]) -> Optional[str]:
    for s in existing:
        if s.slot_id == candidate.slot_id:
            continue
        if circles_overlap(candidate.center, candidate.footprint_radius_m, s.center, s.footprint_radius_m):
            return str(s.slot_id)
    return None


def new_slot_overlaps_existing(new: Slot, existing: Iterable[Slot]) -> Optional[str]:
    return candidate_conflicts_with_list(new, existing)
