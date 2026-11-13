from __future__ import annotations

from typing import Iterable, Optional

from src.domain.models import Drone, Slot
from src.engine.slot_policy import (
    slot_available_for_drone,
    resolved_battery_kwh,
    effective_charge_kw,
    charge_time_seconds,
)


class DockScheduler:
    def _calculate_dwell_time(self, drone: Drone, slot: Slot) -> float:
        """计算预计停靠时长（秒）"""
        if drone.spec is None:
            return 0.0

        battery_kwh = resolved_battery_kwh(drone.spec)
        charge_kw = effective_charge_kw(slot, drone.spec)
        dwell_seconds = charge_time_seconds(drone.battery_percent, battery_kwh, charge_kw)

        return dwell_seconds

    def _check_model_support(self, slot: Slot, drone: Drone) -> bool:
        """判断机位是否支持该机型（预留接口，目前返回True）"""
        # 未来可以在这里添加机型白名单/黑名单逻辑
        return True

    def _check_size_fit(self, slot: Slot, drone: Drone) -> bool:
        """判断尺寸是否满足"""
        if drone.spec is None:
            return True
        return float(drone.spec.size) <= float(slot.max_drone_size_m) + 1e-9

    def _check_power_fit(self, slot: Slot, drone: Drone) -> bool:
        """判断功率是否满足"""
        if drone.spec is None:
            return True
        # 机位能提供的功率必须 >= 无人机最低需求的一定比例（如50%）
        available_power = min(float(slot.station_charge_kw), float(slot.station_charge_cap_kw))
        required_power = float(drone.spec.required_power)
        return available_power >= required_power * 0.5

    def _check_slot_idle(self, slot: Slot, drone: Drone, now: float) -> bool:
        """判断机位是否空闲"""
        return slot.occupied_by is None or slot.occupied_until <= now or slot.occupied_by == drone.drone_id

    def assign_slot(self, drone: Drone, slots: Iterable[Slot], now: float) -> Optional[Slot]:
        """
        新的分配算法：
        1. 根据机型解析尺寸、功率、电池容量
        2. 计算预计停靠时长
        3. 判断机位是否支持该机型
        4. 判断尺寸是否满足
        5. 判断功率是否满足
        6. 判断机位是否空闲
        7. 按优先级排序
        8. 同优先级按预计停靠时长排序
        9. best-fit 选择最小满足机位
        """
        if drone.spec is None:
            return None

        # 筛选满足所有条件的候选机位
        candidates = []
        for slot in slots:
            # 3. 判断机位是否支持该机型
            if not self._check_model_support(slot, drone):
                continue

            # 4. 判断尺寸是否满足
            if not self._check_size_fit(slot, drone):
                continue

            # 5. 判断功率是否满足
            if not self._check_power_fit(slot, drone):
                continue

            # 6. 判断机位是否空闲
            if not self._check_slot_idle(slot, drone, now):
                continue

            # 2. 计算预计停靠时长
            dwell_time = self._calculate_dwell_time(drone, slot)

            candidates.append({
                'slot': slot,
                'dwell_time': dwell_time,
                'size': float(slot.max_drone_size_m),
            })

        if not candidates:
            return None

        # 7. 按优先级排序（无人机优先级）
        # 8. 同优先级按预计停靠时长排序（停靠时间短的优先）
        # 9. best-fit 选择最小满足机位（尺寸最接近的）
        candidates.sort(key=lambda c: (
            -drone.priority,           # 优先级高的优先（降序）
            c['dwell_time'],           # 停靠时间短的优先（升序）
            c['size'],                 # 尺寸小的优先（best-fit，升序）
        ))

        return candidates[0]['slot']

    def describe_assignment(self, drone: Drone, chosen: Slot, slots: Iterable[Slot], now: float) -> str:
        """说明「为何预约该机位」"""
        if drone.spec is None:
            return ""

        # 计算停靠时长
        dwell_time = self._calculate_dwell_time(drone, chosen)
        battery_kwh = resolved_battery_kwh(drone.spec)
        charge_kw = effective_charge_kw(chosen, drone.spec)

        lines: list[str] = []
        lines.append(
            f"为何预约「{chosen.slot_id} · {chosen.display_name}」："
        )
        lines.append(
            f"1. 优先级：{drone.priority}（数值越大优先级越高，优先分配）"
        )
        lines.append(
            f"2. 停靠时长：电池容量 {battery_kwh:.2f}kWh，原始电量 {drone.battery_percent:.0f}%，"
            f"预计停靠 {dwell_time/60:.1f}分钟（停靠时间短的优先）"
        )
        lines.append(
            f"3. Best-Fit匹配：尺寸 {drone.spec.size:.2f}m ≤ 机位上限 {chosen.max_drone_size_m:.2f}m"
            f"（选择最小满足的机位，避免资源浪费）"
        )
        lines.append(
            f"4. 功率匹配：需求 {drone.spec.required_power:.1f}kW，机位可提供 {charge_kw:.1f}kW"
        )
        lines.append(
            f"5. 分配策略：在所有满足条件的机位中，按「优先级 → 停靠时长 → 最小尺寸」排序后选择"
        )

        return "\n".join(lines)
