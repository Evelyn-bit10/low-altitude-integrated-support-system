"""机位调度器 — 最佳匹配算法：按机型→尺寸→功率→空闲筛选，优先分配最优机位。"""
from __future__ import annotations

from typing import List, Optional, Tuple

from engine.sim_models import Drone, Slot
from engine.slot_policy import slot_accepts_drone


class DockScheduler:
    def assign_slot(self, drone: Drone, slots: List[Slot], now: float) -> Optional[Slot]:
        candidates: List[Tuple[Slot, bool]] = []
        for s in slots:
            if not slot_accepts_drone(s, drone, now):
                continue
            free = s.occupied_by is None or s.occupied_until <= now
            candidates.append((s, free))

        if not candidates:
            return None

        def sort_key(item: Tuple[Slot, bool]) -> tuple:
            s, free = item
            priority = 0 if free else 1
            dwell = s.occupied_until - now if not free else 0.0
            return (priority, -s.station_charge_kw, dwell, -s.max_drone_size_m)

        candidates.sort(key=sort_key)
        best_slot, _ = candidates[0]
        self._describe(drone, best_slot, candidates)
        return best_slot

    def _describe(self, drone: Drone, slot: Slot, candidates: list) -> None:
        free_count = sum(1 for _, f in candidates if f)
        drone.assignment_rationale = (
            f"已分配机位 {slot.slot_id} ({slot.name})，{len(candidates)} 个候选中选择最优"
        )

    def describe_assignment(self, drone: Drone, assigned_slot: Slot, slots: List[Slot], now: float) -> str:
        """生成机位分配原因说明，供 UI 显示使用。"""
        candidates: List[Tuple[Slot, bool]] = []
        for s in slots:
            if not slot_accepts_drone(s, drone, now):
                continue
            free = s.occupied_by is None or s.occupied_until <= now
            candidates.append((s, free))
        free_count = sum(1 for _, f in candidates if f)
        lines = []
        lines.append(f"无人机 {drone.drone_id}")
        if drone.spec:
            lines.append(f"  尺寸: {drone.spec.size:.2f}m  |  需求功率: {drone.spec.required_power:.1f}kW")
        lines.append(f"  优先级: {drone.priority}  |  当前电量: {drone.battery_percent:.0f}%")
        lines.append(f"  候选机位: {len(candidates)} 个（空闲 {free_count} 个）")
        lines.append(f"  分配结果: {assigned_slot.slot_id} ({assigned_slot.name})")
        return "\n".join(lines)
