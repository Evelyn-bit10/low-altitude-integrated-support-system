"""无人机信息卡（参考 drone_ground_station/ui/drone_card，PySide6）。"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class GcsDroneInfoCard(QFrame):
    remove_clicked = Signal(str)
    connect_clicked = Signal(str, bool)
    assign_stand_clicked = Signal(str)
    release_stand_clicked = Signal(str)
    pilot_info_clicked = Signal(str)
    mavlink_settings_clicked = Signal(str)

    def __init__(self, drone_config: dict[str, Any], *, sim_mode: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.drone_id = str(drone_config["id"])
        self.drone_name = str(drone_config.get("name", self.drone_id))
        self.drone_emoji = str(drone_config.get("emoji", "✈️"))
        self.drone_model = str(drone_config.get("model", "自定义无人机"))
        self.port = str(drone_config.get("port", "COM?"))
        self.baud = int(drone_config.get("baud", 57600))
        self.sim_mode = bool(sim_mode)
        self.is_connected = False
        self.assigned_stand: Optional[str] = None
        self.stand_info: Optional[dict[str, Any]] = None
        self._setup_ui()
        self.set_aircraft_spec(
            float(drone_config.get("size_m", 0.0) or 0.0),
            float(drone_config.get("charge_kw", 0.0) or 0.0),
            float(drone_config.get("battery_kwh", 0.0) or 0.0),
            show_auto=self.sim_mode,
        )

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet(
            """
            GcsDroneInfoCard { background-color: #ffffff; border: 1px solid #dcdfe6; border-radius: 8px; }
            GcsDroneInfoCard[connected="true"] { border: 2px solid #67C23A; background-color: #f0f9eb; }
            GcsDroneInfoCard[connected="false"] { border: 1px solid #dcdfe6; }
            GcsDroneInfoCard[assigned="true"] { border: 2px solid #95d475; background-color: #f3faef; }
            QLabel { font-family: "SimSun", "Microsoft YaHei", sans-serif; }
            QLabel#titleLabel { font-size: 16px; font-weight: bold; color: #303133; padding: 4px 0px; }
            QLabel#standLabel { font-size: 12px; color: #67C23A; background-color: #f0f9eb; padding: 4px 10px;
                border-radius: 12px; font-weight: bold; }
            QLabel#standLabel[type="indoor"] { background-color: #e1f5fe; color: #0288d1; }
            QLabel#standLabel[type="outdoor"] { background-color: #e8f5e8; color: #2e7d32; }
            QLabel#titleStandLabel { font-size: 12px; color: #67C23A; background-color: #f0f9eb; padding: 4px 10px;
                border-radius: 999px; font-weight: bold; }
            QLabel#titleStandLabel[type="indoor"] { background-color: #e1f5fe; color: #0288d1; }
            QLabel#titleStandLabel[type="outdoor"] { background-color: #e8f5e8; color: #2e7d32; }
            QLabel#valueLabel { font-size: 16px; font-weight: bold; color: #409EFF; background-color: #f4f4f5;
                padding: 8px 2px; border-radius: 6px; margin-top: 2px; }
            QLabel#infoLabel { font-size: 13px; color: #606266; font-weight: bold; }
            QLabel#portLabel { font-size: 12px; color: #909399; background-color: #f4f4f5; padding: 2px 8px;
                border-radius: 10px; }
            QPushButton#removeBtn { background-color: transparent; border: none; color: #f56c6c; font-size: 16px;
                font-weight: bold; padding: 2px 6px; border-radius: 4px; }
            QPushButton#removeBtn:hover { background-color: #fef0f0; }
            QPushButton#assignBtn { background-color: #409EFF; color: white; border: none; border-radius: 4px;
                padding: 5px 10px; font-size: 13px; font-weight: bold; min-width: 60px; }
            QPushButton#assignBtn:hover { background-color: #66b1ff; }
            QPushButton#assignBtn[assigned="true"] { background-color: #67C23A; }
            QPushButton#assignBtn[assigned="true"]:hover { background-color: #85ce61; }
            QPushButton#connectBtn { border: none; border-radius: 4px; padding: 5px 10px; font-size: 13px;
                font-weight: bold; min-width: 60px; }
            QPushButton#connectBtn[connected="true"] { background-color: #f56c6c; color: white; }
            QPushButton#connectBtn[connected="true"]:hover { background-color: #f78989; }
            QPushButton#connectBtn[connected="false"] { background-color: #67C23A; color: white; }
            QPushButton#connectBtn[connected="false"]:hover { background-color: #85ce61; }
            QPushButton#releaseBtn { background-color: #f56c6c; color: white; border: none; border-radius: 4px;
                padding: 4px 8px; font-size: 12px; margin-top: 4px; }
            QPushButton#releaseBtn:hover { background-color: #f78989; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 7, 8, 7)

        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel(self.drone_emoji))
        title_label = QLabel(self.drone_name)
        title_label.setObjectName("titleLabel")
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_layout.addWidget(title_label)

        self.title_stand_label = QLabel("")
        self.title_stand_label.setObjectName("titleStandLabel")
        self.title_stand_label.hide()
        self.title_stand_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        title_layout.addWidget(self.title_stand_label)

        title_layout.addStretch()
        port_text = "仿真" if self.sim_mode else f"{self.port} @ {self.baud}"
        self.port_label = QLabel(port_text)
        self.port_label.setObjectName("portLabel")
        self.port_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.port_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.port_label.setMaximumWidth(140)
        title_layout.addWidget(self.port_label)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("removeBtn")
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.drone_id))
        title_layout.addWidget(self.remove_btn)
        layout.addLayout(title_layout)

        button_row = QHBoxLayout()
        self.stand_label = QLabel("")
        self.stand_label.setObjectName("standLabel")
        self.stand_label.hide()
        button_row.addWidget(self.stand_label)
        button_row.addStretch()

        self.assign_btn = QPushButton("📋 分配")
        self.assign_btn.setObjectName("assignBtn")
        self.assign_btn.setProperty("assigned", False)
        self.assign_btn.clicked.connect(lambda: self.assign_stand_clicked.emit(self.drone_id))
        button_row.addWidget(self.assign_btn)

        self.pilot_btn = QPushButton("👨‍✈️ 飞手")
        self.pilot_btn.setObjectName("assignBtn")
        self.pilot_btn.clicked.connect(lambda: self.pilot_info_clicked.emit(self.drone_id))
        button_row.addWidget(self.pilot_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setProperty("connected", False)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        if self.sim_mode:
            self.connect_btn.setEnabled(False)
            self.connect_btn.setToolTip("仿真无人机无需串口连接")
            self.connect_btn.setText("—")
        button_row.addWidget(self.connect_btn)

        self.mavlink_cfg_btn = QPushButton("⚙ MAVLink")
        self.mavlink_cfg_btn.setObjectName("assignBtn")
        self.mavlink_cfg_btn.setToolTip("修改 COM 口 / 波特率（保存后需重新连接）")
        if self.sim_mode:
            self.mavlink_cfg_btn.setEnabled(False)
            self.mavlink_cfg_btn.setToolTip("仿真机不使用 MAVLink 串口")
        else:
            self.mavlink_cfg_btn.clicked.connect(lambda: self.mavlink_settings_clicked.emit(self.drone_id))
        button_row.addWidget(self.mavlink_cfg_btn)
        layout.addLayout(button_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #ebeef5; max-height: 1px; border: none; margin: 4px 0;")
        layout.addWidget(line)

        self.lat_value = QLabel("--")
        self.lng_value = QLabel("--")
        self.alt_value = QLabel("--")
        self.battery_value = QLabel("--")
        self.charge_power_value = QLabel("--")
        self.sats_value = QLabel("--")

        coord_layout = QHBoxLayout()
        coord_layout.setSpacing(6)
        coord_layout.addLayout(self._create_data_box("纬度 (Lat)", self.lat_value))
        coord_layout.addLayout(self._create_data_box("经度 (Lng)", self.lng_value))
        layout.addLayout(coord_layout)

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(4)
        stats_layout.addLayout(self._create_data_box("高度(m)", self.alt_value))
        stats_layout.addLayout(self._create_data_box("电量(%)", self.battery_value))
        stats_layout.addLayout(self._create_data_box("充电(W)", self.charge_power_value))
        stats_layout.addLayout(self._create_data_box("卫星", self.sats_value))
        layout.addLayout(stats_layout)

        self.spec_row = QLabel("")
        self.spec_row.setStyleSheet("font-size: 12px; color: #606266; padding: 2px 0;")
        self.spec_row.setWordWrap(True)
        layout.addWidget(self.spec_row)

        self.stand_info_widget = QFrame()
        self.stand_info_widget.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 6px; margin-top: 6px; padding: 6px; }"
        )
        self.stand_info_widget.hide()
        sil = QVBoxLayout(self.stand_info_widget)
        sil.setContentsMargins(6, 6, 6, 6)
        self.stand_detail_label = QLabel()
        self.stand_detail_label.setWordWrap(True)
        self.stand_detail_label.setStyleSheet("font-size: 12px; color: #606266; line-height: 1.5;")
        sil.addWidget(self.stand_detail_label)
        self.release_stand_btn = QPushButton("释放机位")
        self.release_stand_btn.setObjectName("releaseBtn")
        self.release_stand_btn.clicked.connect(self._on_release_stand)
        sil.addWidget(self.release_stand_btn)
        layout.addWidget(self.stand_info_widget)

        self.setProperty("connected", False)
        self.setProperty("assigned", False)

    def _create_data_box(self, label_text: str, value_label: QLabel) -> QVBoxLayout:
        vbox = QVBoxLayout()
        vbox.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setObjectName("infoLabel")
        lbl.setAlignment(Qt.AlignCenter)
        value_label.setObjectName("valueLabel")
        value_label.setAlignment(Qt.AlignCenter)
        vbox.addWidget(lbl)
        vbox.addWidget(value_label)
        return vbox

    def _on_connect_clicked(self) -> None:
        if self.sim_mode:
            return
        self.connect_clicked.emit(self.drone_id, not self.is_connected)

    def _on_release_stand(self) -> None:
        if not self.assigned_stand or not self.stand_info:
            return
        stand_name = self.stand_info.get("name", self.assigned_stand)
        msg = QMessageBox(self.window() or self)
        msg.setWindowTitle("确认释放机位")
        msg.setText(f"确定要释放机位 {stand_name} 吗？\n\n释放后该机位将变为空闲状态。")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.release_stand_clicked.emit(self.drone_id)

    def set_connected(self, connected: bool) -> None:
        if self.sim_mode:
            return
        self.is_connected = connected
        self.connect_btn.setText("断开" if connected else "连接")
        self.connect_btn.setProperty("connected", connected)
        self.setProperty("connected", connected)
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_assigned_stand(self, stand_id: Optional[str], stand_info: Optional[dict[str, Any]] = None) -> None:
        self.assigned_stand = stand_id
        self.stand_info = stand_info
        if stand_id and stand_info:
            stand_type = str(stand_info.get("type", "outdoor"))
            self.title_stand_label.hide()
            self.stand_label.hide()
            self.setProperty("assigned", True)
            self.assign_btn.setText("✓ 已分配")
            self.assign_btn.setProperty("assigned", True)
            stand_name = stand_info.get("name", stand_id)
            detail = f"📌 机位: {stand_name}    ID: {stand_id}\n"
            detail += f"🏷️ 类型: {'室内' if stand_type == 'indoor' else '室外'}\n"
            detail += f"⏰ 分配时间: {stand_info.get('assigned_time', '--')}\n"
            detail += f"📝 描述: {stand_info.get('description', '--')}"
            self.stand_detail_label.setText(detail)
            self.stand_info_widget.show()
        else:
            self.title_stand_label.hide()
            self.stand_label.hide()
            self.setProperty("assigned", False)
            self.assign_btn.setText("📋 分配")
            self.assign_btn.setProperty("assigned", False)
            self.stand_info_widget.hide()
        self.assign_btn.style().unpolish(self.assign_btn)
        self.assign_btn.style().polish(self.assign_btn)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_aircraft_spec(
        self,
        size_m: float,
        charge_kw: float,
        battery_kwh: float,
        *,
        show_auto: bool = False,
    ) -> None:
        if battery_kwh > 1e-9:
            bt = f"{battery_kwh:.3f} kWh"
        elif show_auto:
            bt = "自动估算"
        else:
            bt = "--"
        sz_txt = f"{size_m:.2f} m" if size_m > 1e-6 else "--"
        pw_txt = f"{charge_kw:.1f} kW" if charge_kw > 1e-6 else "--"
        self.spec_row.setText(f"尺寸 {sz_txt}  ·  需求充电 {pw_txt}  ·  电池 {bt}")

    def update_data(
        self,
        lat: Optional[float],
        lng: Optional[float],
        alt: Optional[float],
        battery: Optional[float],
        sats: Optional[int],
        charge_w: Optional[float] = None,
    ) -> None:
        base_style = "QLabel#valueLabel { padding: 8px 2px; border-radius: 6px; "
        self.lat_value.setText(f"{lat:.6f}" if lat is not None else "--")
        self.lng_value.setText(f"{lng:.6f}" if lng is not None else "--")
        self.alt_value.setText(f"{alt:.1f}" if alt is not None else "--")
        if battery is not None and battery >= 0:
            self.battery_value.setText(f"{battery:.0f}")
            if battery < 20:
                self.battery_value.setStyleSheet(base_style + "background-color:#fef0f0; color:#F56C6C;}")
            elif battery < 50:
                self.battery_value.setStyleSheet(base_style + "background-color:#fdf6ec; color:#E6A23C;}")
            else:
                self.battery_value.setStyleSheet(base_style + "background-color:#f0f9eb; color:#67C23A;}")
        else:
            self.battery_value.setText("--")
            self.battery_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")
        if charge_w is not None and charge_w > 0:
            self.charge_power_value.setText(f"{charge_w:.0f}")
            self.charge_power_value.setStyleSheet(base_style + "background-color:#ecf5ff; color:#409EFF;}")
        elif charge_w is not None and charge_w <= 0:
            self.charge_power_value.setText("0")
            self.charge_power_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#909399;}")
        else:
            self.charge_power_value.setText("--")
            self.charge_power_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")
        if sats is not None and sats >= 0:
            self.sats_value.setText(f"{sats:.0f}")
            if sats < 6:
                self.sats_value.setStyleSheet(base_style + "background-color:#fdf6ec; color:#E6A23C;}")
            else:
                self.sats_value.setStyleSheet(base_style + "background-color:#f0f9eb; color:#67C23A;}")
        else:
            self.sats_value.setText("--")
            self.sats_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")

    def clear_data(self) -> None:
        self.update_data(None, None, None, None, None, None)

    def set_port_baud(self, port: str, baud: int) -> None:
        self.port = port
        self.baud = baud
        if not self.sim_mode:
            self.port_label.setText(f"{self.port} @ {self.baud}")
