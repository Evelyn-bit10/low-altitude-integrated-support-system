"""仿真控制面板 — 嵌入主窗口右侧面板的仿真控制 UI。"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QTextEdit, QSlider, QGroupBox,
    QScrollArea, QFrame, QSizePolicy, QCheckBox, QLineEdit,
)


class SimControlPanel(QWidget):
    """仿真控制面板：场景按钮、播放控制、速度调节、无人机干预、告警日志。"""

    # 控制信号
    scenarioRequested = pyqtSignal(int)    # 加载演示场景 (0-3)
    startRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    resetRequested = pyqtSignal()
    speedChanged = pyqtSignal(float)       # 速度倍率

    # 无人机干预信号
    droneDeviateRequested = pyqtSignal(str)  # drone_id
    droneRecoverRequested = pyqtSignal(str)
    droneFollowRequested = pyqtSignal(str)

    # 虚拟地面站定位
    virtualGcsChanged = pyqtSignal(bool, float, float)  # enabled, lat, lng

    SIM_SPEED_LABELS = {1: "1x", 3: "3x", 6: "6x", 10: "10x", 20: "20x"}

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ---- 场景选择 ----
        scenario_group = QGroupBox("🎬 演示场景")
        scenario_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 8px; padding-top: 16px; }")
        slayout = QVBoxLayout(scenario_group)
        slayout.setSpacing(4)

        scenarios = [
            ("🚁 正常进场停靠", "随机生成无人机，自动分配机位并进场停靠充电"),
            ("⭐ 混合优先级", "不同优先级的无人机竞争机位"),
            ("⚡ 单机快速演示", "单架无人机完整生命周期演示"),
            ("🔥 高密度队列", "多架无人机排队进场"),
        ]
        for i, (title, desc) in enumerate(scenarios):
            btn = QPushButton(title)
            btn.setToolTip(desc)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px 10px; border: 1px solid #e4e7ed; "
                "border-radius: 4px; background: #fafafa; } "
                "QPushButton:hover { background: #ecf5ff; border-color: #409EFF; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self.scenarioRequested.emit(idx))
            slayout.addWidget(btn)

        layout.addWidget(scenario_group)

        # ---- 播放控制 ----
        ctrl_group = QGroupBox("▶ 仿真控制")
        ctrl_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 8px; padding-top: 16px; }")
        cl = QVBoxLayout(ctrl_group)
        cl.setSpacing(6)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setStyleSheet(self._btn_green_style())
        self.btn_start.clicked.connect(lambda: self.startRequested.emit())

        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setStyleSheet(self._btn_orange_style())
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(lambda: self.pauseRequested.emit())

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setStyleSheet(self._btn_red_style())
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self.stopRequested.emit())

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_pause)
        btn_row.addWidget(self.btn_stop)
        cl.addLayout(btn_row)

        # 速度调节
        speed_row = QHBoxLayout()
        self.speed_label = QLabel("速度: 1x")
        self.speed_label.setMinimumWidth(60)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(0, 4)  # 对应 1x, 3x, 6x, 10x, 20x
        self.speed_slider.setValue(0)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self.speed_slider)
        cl.addLayout(speed_row)

        # 仿真时间
        self.time_label = QLabel("⏱ 仿真时间: 0.0s")
        self.time_label.setStyleSheet("color: #909399; font-size: 12px;")
        cl.addWidget(self.time_label)

        layout.addWidget(ctrl_group)

        # ---- 无人机干预 ----
        drone_group = QGroupBox("🛸 无人机干预")
        drone_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 8px; padding-top: 16px; }")
        dl = QVBoxLayout(drone_group)
        dl.setSpacing(4)

        self.drone_list = QListWidget()
        self.drone_list.setMaximumHeight(160)
        self.drone_list.setStyleSheet(
            "QListWidget { border: 1px solid #e4e7ed; border-radius: 4px; font-size: 12px; }"
        )
        dl.addWidget(self.drone_list)

        intv_btn_row = QHBoxLayout()
        self.btn_deviate = QPushButton("↗ 偏航")
        self.btn_deviate.setStyleSheet(self._btn_orange_style())
        self.btn_deviate.clicked.connect(lambda: self._emit_drone_action("deviate"))
        self.btn_deviate.setEnabled(False)

        self.btn_recover = QPushButton("↺ 恢复")
        self.btn_recover.setStyleSheet(self._btn_green_style())
        self.btn_recover.clicked.connect(lambda: self._emit_drone_action("recover"))
        self.btn_recover.setEnabled(False)

        self.btn_force_follow = QPushButton("🎯 贴合路径")
        self.btn_force_follow.setStyleSheet(self._btn_blue_style())
        self.btn_force_follow.clicked.connect(lambda: self._emit_drone_action("follow"))
        self.btn_force_follow.setEnabled(False)

        intv_btn_row.addWidget(self.btn_deviate)
        intv_btn_row.addWidget(self.btn_recover)
        intv_btn_row.addWidget(self.btn_force_follow)
        dl.addLayout(intv_btn_row)

        layout.addWidget(drone_group)

        # ---- 告警日志 ----
        alert_group = QGroupBox("⚠ 告警日志")
        alert_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 8px; padding-top: 16px; }")
        al = QVBoxLayout(alert_group)

        self.alert_log = QTextEdit()
        self.alert_log.setReadOnly(True)
        self.alert_log.setMaximumHeight(140)
        self.alert_log.setStyleSheet(
            "QTextEdit { border: 1px solid #e4e7ed; border-radius: 4px; font-size: 11px; "
            "font-family: Consolas, monospace; background: #fdf6ec; }"
        )
        al.addWidget(self.alert_log)

        layout.addWidget(alert_group)

        # ---- 虚拟地面站定位 ----
        gcs_group = QGroupBox("📍 虚拟地面站定位")
        gcs_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 8px; padding-top: 16px; }")
        gl = QVBoxLayout(gcs_group)
        gl.setSpacing(4)

        enable_row = QHBoxLayout()
        self.chk_virtual_gcs = QCheckBox("启用虚拟地面站")
        self.chk_virtual_gcs.setStyleSheet("QCheckBox { font-size: 12px; }")
        self.chk_virtual_gcs.toggled.connect(self._on_virtual_gcs_toggled)
        enable_row.addWidget(self.chk_virtual_gcs)
        enable_row.addStretch()
        gl.addLayout(enable_row)

        coord_row = QHBoxLayout()
        coord_row.addWidget(QLabel("纬度:"))
        self.edit_gcs_lat = QLineEdit()
        self.edit_gcs_lat.setPlaceholderText("如 29.52")
        self.edit_gcs_lat.setStyleSheet("QLineEdit { border: 1px solid #dcdfe6; border-radius: 4px; padding: 4px 6px; font-size: 11px; }")
        self.edit_gcs_lat.setEnabled(False)
        coord_row.addWidget(self.edit_gcs_lat)
        coord_row.addWidget(QLabel("经度:"))
        self.edit_gcs_lng = QLineEdit()
        self.edit_gcs_lng.setPlaceholderText("如 106.56")
        self.edit_gcs_lng.setStyleSheet("QLineEdit { border: 1px solid #dcdfe6; border-radius: 4px; padding: 4px 6px; font-size: 11px; }")
        self.edit_gcs_lng.setEnabled(False)
        coord_row.addWidget(self.edit_gcs_lng)
        gl.addLayout(coord_row)

        self.btn_apply_gcs = QPushButton("📍 应用坐标")
        self.btn_apply_gcs.setStyleSheet(self._btn_blue_style())
        self.btn_apply_gcs.setEnabled(False)
        self.btn_apply_gcs.clicked.connect(self._apply_virtual_gcs)
        gl.addWidget(self.btn_apply_gcs)

        self.lbl_gcs_status = QLabel("")
        self.lbl_gcs_status.setStyleSheet("color: #909399; font-size: 10px;")
        self.lbl_gcs_status.setWordWrap(True)
        gl.addWidget(self.lbl_gcs_status)

        layout.addWidget(gcs_group)

        layout.addStretch()

    # ------------------------------------------------------------------
    # 外部调用接口
    # ------------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        if running:
            self.btn_pause.setText("⏸ 暂停")
        else:
            self.btn_pause.setText("⏸ 暂停")

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.btn_pause.setText("▶ 继续")
        else:
            self.btn_pause.setText("⏸ 暂停")

    def set_time(self, sim_time: float) -> None:
        self.time_label.setText(f"⏱ 仿真时间: {sim_time:.1f}s")

    def update_drone_list(self, drones: list) -> None:
        """更新无人机干预列表。drones: [{"id": str, "status": str, "demo_route_mode": str}, ...]"""
        self.drone_list.clear()
        for d in drones:
            status_emoji = {
                "approaching": "🔵", "waiting": "🟡", "inbound": "🟢",
                "docked": "⚪", "waiting_outbound": "🟠", "outbound": "🟣",
                "finished": "✅",
            }.get(d.get("status", ""), "❓")
            mode = d.get("demo_route_mode", "follow")
            item = QListWidgetItem(f"{status_emoji} {d['id']}  [{mode}]")
            item.setData(Qt.UserRole, d["id"])
            self.drone_list.addItem(item)
        has_selection = self.drone_list.count() > 0
        self.btn_deviate.setEnabled(has_selection)
        self.btn_recover.setEnabled(has_selection)
        self.btn_force_follow.setEnabled(has_selection)

    def add_alert(self, message: str) -> None:
        self.alert_log.append(message)
        # 限制日志行数
        if self.alert_log.document().blockCount() > 200:
            self.alert_log.clear()

    def clear_alerts(self) -> None:
        self.alert_log.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_virtual_gcs_toggled(self, checked: bool) -> None:
        self.edit_gcs_lat.setEnabled(checked)
        self.edit_gcs_lng.setEnabled(checked)
        self.btn_apply_gcs.setEnabled(checked)
        if not checked:
            self.lbl_gcs_status.setText("")
            self.virtualGcsChanged.emit(False, 0.0, 0.0)

    def _apply_virtual_gcs(self) -> None:
        try:
            lat = float(self.edit_gcs_lat.text().strip())
            lng = float(self.edit_gcs_lng.text().strip())
            if not (-90 <= lat <= 90):
                self.lbl_gcs_status.setText("❌ 纬度需在 -90~90 之间")
                return
            if not (-180 <= lng <= 180):
                self.lbl_gcs_status.setText("❌ 经度需在 -180~180 之间")
                return
            self.lbl_gcs_status.setText(f"✅ 已设置: {lat:.5f}, {lng:.5f}")
            self.virtualGcsChanged.emit(True, lat, lng)
        except ValueError:
            self.lbl_gcs_status.setText("❌ 请输入有效数字")

    def set_gcs_coords(self, lat: float, lng: float) -> None:
        """外部设置默认值（从配置读取）。"""
        self.edit_gcs_lat.setText(f"{lat:.6f}")
        self.edit_gcs_lng.setText(f"{lng:.6f}")

    def _on_speed_changed(self, value: int) -> None:
        speeds = [1, 3, 6, 10, 20]
        mult = speeds[value]
        self.speed_label.setText(f"速度: {mult}x")
        self.speedChanged.emit(float(mult))

    def _emit_drone_action(self, action: str) -> None:
        item = self.drone_list.currentItem()
        if not item:
            return
        drone_id = item.data(Qt.UserRole)
        if action == "deviate":
            self.droneDeviateRequested.emit(drone_id)
        elif action == "recover":
            self.droneRecoverRequested.emit(drone_id)
        elif action == "follow":
            self.droneFollowRequested.emit(drone_id)

    # ------------------------------------------------------------------
    # 样式工具
    # ------------------------------------------------------------------

    @staticmethod
    def _btn_green_style() -> str:
        return (
            "QPushButton { background-color: #67C23A; color: white; border: none; border-radius: 4px; "
            "padding: 6px 10px; font-weight: bold; } "
            "QPushButton:hover { background-color: #85ce61; } "
            "QPushButton:disabled { background-color: #c0c4cc; }"
        )

    @staticmethod
    def _btn_orange_style() -> str:
        return (
            "QPushButton { background-color: #E6A23C; color: white; border: none; border-radius: 4px; "
            "padding: 6px 10px; font-weight: bold; } "
            "QPushButton:hover { background-color: #ebb563; } "
            "QPushButton:disabled { background-color: #c0c4cc; }"
        )

    @staticmethod
    def _btn_red_style() -> str:
        return (
            "QPushButton { background-color: #F56C6C; color: white; border: none; border-radius: 4px; "
            "padding: 6px 10px; font-weight: bold; } "
            "QPushButton:hover { background-color: #f78989; } "
            "QPushButton:disabled { background-color: #c0c4cc; }"
        )

    @staticmethod
    def _btn_blue_style() -> str:
        return (
            "QPushButton { background-color: #409EFF; color: white; border: none; border-radius: 4px; "
            "padding: 6px 10px; font-weight: bold; } "
            "QPushButton:hover { background-color: #66b1ff; } "
            "QPushButton:disabled { background-color: #c0c4cc; }"
        )
