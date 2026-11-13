"""机位分配对话框（简化版，行为对齐地面站：列表选机位 → 确认分配）。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QButtonGroup,
)

from src.domain.models import Drone, Slot
from src.engine.slot_policy import slot_accepts_drone


class StandAssignDialog(QDialog):
    def __init__(
        self,
        drone_id: str,
        drone_name: str,
        drone_model: str,
        slots: List[Slot],
        now: float,
        compat_drone: Optional[Drone] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._drone_id = drone_id
        self._drone_name = drone_name
        self._drone_model = drone_model
        self._slots = slots
        self._now = now
        self._compat_drone = compat_drone
        self._selected_slot_id: Optional[str] = None
        self.setWindowTitle(f"机位分配 - {drone_name}")
        self.setMinimumSize(640, 420)
        self._build_ui()
        self._load_table("all")

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        title = QLabel(f"✈️ 无人机 {self._drone_name}（{self._drone_id}）  ·  型号 {self._drone_model}")
        title.setStyleSheet("font-size: 15px; font-weight: bold; padding: 8px;")
        lay.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选:"))
        self._bg = QButtonGroup(self)
        self._rb_all = QRadioButton("全部机位")
        self._rb_in = QRadioButton("室内")
        self._rb_out = QRadioButton("室外")
        self._rb_all.setChecked(True)
        for rb in (self._rb_all, self._rb_in, self._rb_out):
            self._bg.addButton(rb)
            filter_row.addWidget(rb)
        self._rb_all.clicked.connect(lambda: self._rb_all.isChecked() and self._load_table("all"))
        self._rb_in.clicked.connect(lambda: self._rb_in.isChecked() and self._load_table("indoor"))
        self._rb_out.clicked.connect(lambda: self._rb_out.isChecked() and self._load_table("outdoor"))
        filter_row.addStretch(1)
        lay.addLayout(filter_row)
        hint = QLabel("仅显示当前机型尺寸可容纳的空闲/可预约机位。")
        hint.setStyleSheet("color:#909399;font-size:11px;padding-left:2px;")
        lay.addWidget(hint)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["机位ID", "名称", "类型", "状态", "占用者"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self._table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _slot_available(self, slot: Slot) -> bool:
        if slot.occupied_by is None:
            return True
        if slot.occupied_until <= self._now:
            return True
        return slot.occupied_by == self._drone_id

    def _load_table(self, flt: str) -> None:
        self._table.setRowCount(0)
        for slot in self._slots:
            st = slot.stand_type or "outdoor"
            if flt == "indoor" and st != "indoor":
                continue
            if flt == "outdoor" and st != "outdoor":
                continue
            if self._compat_drone is not None and not slot_accepts_drone(slot, self._compat_drone, self._now):
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            avail = self._slot_available(slot)
            occ = slot.occupied_by or ""
            if not avail:
                status = "已占用"
            elif occ == self._drone_id:
                status = "已预约本机"
            else:
                status = "空闲"
            self._table.setItem(row, 0, QTableWidgetItem(slot.slot_id))
            self._table.setItem(row, 1, QTableWidgetItem(slot.display_name))
            self._table.setItem(row, 2, QTableWidgetItem("室内" if st == "indoor" else "室外"))
            self._table.setItem(row, 3, QTableWidgetItem(status))
            self._table.setItem(row, 4, QTableWidgetItem(occ if occ else "—"))

    def _on_accept(self) -> None:
        r = self._table.currentRow()
        if r < 0:
            QMessageBox.warning(self, "机位分配", "请先选择一行机位。")
            return
        id_item = self._table.item(r, 0)
        if not id_item:
            return
        sid = id_item.text().strip()
        slot = next((s for s in self._slots if s.slot_id == sid), None)
        if slot is None:
            return
        if not self._slot_available(slot):
            QMessageBox.warning(self, "机位分配", "该机位已被占用，请另选。")
            return
        self._selected_slot_id = sid
        self.accept()

    def selected_slot_id(self) -> Optional[str]:
        return self._selected_slot_id

    @staticmethod
    def stand_info_dict(slot: Slot) -> dict:
        return {
            "id": slot.slot_id,
            "name": slot.display_name,
            "type": slot.stand_type or "outdoor",
            "description": slot.description or "—",
            "assigned_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
