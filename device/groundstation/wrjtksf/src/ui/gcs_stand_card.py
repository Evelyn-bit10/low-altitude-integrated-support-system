"""机位信息卡（逻辑与 drone_ground_station/ui/stand_card 对齐，PySide6）。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.domain.models import Slot


class GcsStandInfoCard(QFrame):
    release_stand_clicked = Signal(str)
    delete_stand_clicked = Signal(str)
    edit_stand_clicked = Signal(str)

    def __init__(self, stand_id: str, name: str, stand_type: str, parent=None) -> None:
        super().__init__(parent)
        self.stand_id = str(stand_id)
        self._name = name
        self.stand_type = stand_type if stand_type in ("indoor", "outdoor") else "outdoor"
        self.occupied_drone_id: Optional[str] = None
        self._build_ui()
        self._apply_static_content()
        self.set_occupied(None)

    def _build_ui(self) -> None:
        self.setObjectName("standInfoCard")
        self.setStyleSheet(
            """
            #standInfoCard {
                background-color: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 8px;
            }
            #standInfoCard[occupied="true"] {
                border: 2px solid #F56C6C;
            }
            QLabel { font-family: "SimSun", "Microsoft YaHei", sans-serif; }
            QLabel#titleLabel {
                font-size: 14px;
                font-weight: bold;
                color: #303133;
                padding: 2px 0;
            }
            QLabel#typeTag {
                font-size: 12px;
                color: #67C23A;
                background-color: #f0f9eb;
                padding: 4px 10px;
                border-radius: 999px;
                font-weight: bold;
            }
            QLabel#typeTag[type="indoor"] {
                background-color: #e1f5fe;
                color: #0288d1;
            }
            QLabel#typeTag[type="outdoor"] {
                background-color: #e8f5e8;
                color: #2e7d32;
            }
            QLabel#statusLabel {
                font-size: 12px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 999px;
            }
            QLabel#droneValueLabel {
                font-size: 13px;
                color: #606266;
            }
            QPushButton#releaseBtn {
                background-color: #F56C6C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton#releaseBtn:disabled {
                background-color: #f5f7fa;
                color: #909399;
            }
            QPushButton#releaseBtn:hover:!disabled {
                background-color: #f78989;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 7, 8, 7)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(QLabel("📍"))
        self._title_label = QLabel()
        self._title_label.setObjectName("titleLabel")
        title_row.addWidget(self._title_label, 1)
        self._type_tag = QLabel()
        self._type_tag.setObjectName("typeTag")
        self._type_tag.setProperty("type", self.stand_type)
        title_row.addWidget(self._type_tag)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                border: none;
                color: #f56c6c;
                font-size: 16px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #fef0f0; }
            """
        )
        self._delete_btn.clicked.connect(lambda: self.delete_stand_clicked.emit(self.stand_id))
        title_row.addWidget(self._delete_btn)
        layout.addLayout(title_row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        self._status_label = QLabel()
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        meta_row.addWidget(self._status_label, 1)
        self._drone_value_label = QLabel("--")
        self._drone_value_label.setObjectName("droneValueLabel")
        meta_row.addWidget(self._drone_value_label, 2)
        layout.addLayout(meta_row)

        self._constraint_label = QLabel()
        self._constraint_label.setObjectName("droneValueLabel")
        self._constraint_label.setWordWrap(True)
        self._constraint_label.setStyleSheet("font-size: 11px; color: #606266;")
        layout.addWidget(self._constraint_label)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self._edit_btn = QPushButton("编辑")
        self._edit_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton:hover { background-color: #66b1ff; }
            """
        )
        self._edit_btn.clicked.connect(lambda: self.edit_stand_clicked.emit(self.stand_id))
        self._release_btn = QPushButton("释放机位")
        self._release_btn.setObjectName("releaseBtn")
        self._release_btn.clicked.connect(lambda: self.release_stand_clicked.emit(self.stand_id))
        bottom_row.addWidget(self._edit_btn)
        bottom_row.addWidget(self._release_btn)
        layout.addLayout(bottom_row)

    def _apply_static_content(self) -> None:
        self._title_label.setText(f"{self._name}（{self.stand_id}）")
        self._type_tag.setText("室内" if self.stand_type == "indoor" else "室外")
        self._type_tag.setProperty("type", self.stand_type)

    def set_name(self, name: str) -> None:
        self._name = name
        self._apply_static_content()

    def set_stand_type(self, stand_type: str) -> None:
        self.stand_type = stand_type if stand_type in ("indoor", "outdoor") else "outdoor"
        self._type_tag.setProperty("type", self.stand_type)
        self._apply_static_content()

    def apply_slot_constraints(self, slot: Optional[Slot]) -> None:
        if slot is None:
            self._constraint_label.setText("")
            return
        self._constraint_label.setText(
            f"保护区 R={slot.footprint_radius_m:.0f} m  ·  最大机型 ≤{slot.max_drone_size_m:.1f} m\n"
            f"充电 {slot.station_charge_kw:.1f} kW（上限 {slot.station_charge_cap_kw:.1f} kW）"
        )

    def set_occupied(self, drone_id: Optional[str]) -> None:
        self.occupied_drone_id = str(drone_id) if drone_id else None
        if self.occupied_drone_id:
            self.setProperty("occupied", True)
            self._status_label.setText("🔴 已占用 / 已分配")
            self._status_label.setStyleSheet("background-color: rgba(245,108,108,0.12); color: #F56C6C;")
            self._drone_value_label.setText(f"占用/预约：{self.occupied_drone_id}")
            self._release_btn.setEnabled(True)
        else:
            self.setProperty("occupied", False)
            self._status_label.setText("🟢 空闲")
            self._status_label.setStyleSheet("background-color: rgba(103,194,35,0.12); color: #67C23A;")
            self._drone_value_label.setText("--")
            self._release_btn.setEnabled(False)
        self.style().unpolish(self)
        self.style().polish(self)
