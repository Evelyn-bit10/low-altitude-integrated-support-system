from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSize, QPropertyAnimation
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from src.domain.models import DroneStatus, NoFlyZone, Obstacle, RectangleZone, Slot, Vec2
from src.engine.simulation_engine import SimulationEngine
from src.services.adsb_serial import ADSBSerialReader, clear_adsb_cache, decode_and_update, get_aircraft_snapshot
from src.engine.slot_policy import candidate_conflicts_with_list, resolved_battery_kwh
from src.services.pilot_mailer import PilotMailer
from src.services.geo_math import world_meters_to_wgs84
from src.services.location_service import get_location_sync
from src.services.weather_service import WeatherCache
from src.ui.gcs_drone_card import GcsDroneInfoCard
from src.ui.gcs_stand_card import GcsStandInfoCard
from src.ui.gcs_weather_card import GcsWeatherCard
from src.ui.gcs_sensor_card import GcsSensorCard
from src.ui.map_canvas import MapCanvas
from src.ui.radar_widget import RadarWidget
from src.ui.add_real_drone_dialog import AddRealDroneDialog
from src.ui.pilot_info_dialog import PilotInfoDialog
from src.ui.stand_assign_dialog import StandAssignDialog
from src.workers.drone_telemetry_worker import DroneTelemetryWorker

_DEMO_STATUS_CN: Dict[DroneStatus, str] = {
    DroneStatus.APPROACHING: "接近并驶向等待区",
    DroneStatus.WAITING: "在等待区内排队，等待放行进场",
    DroneStatus.INBOUND: "沿进场航线飞向机位",
    DroneStatus.DOCKED: "已降落，正在充电",
    DroneStatus.WAITING_OUTBOUND: "充电完成，排队离场",
    DroneStatus.OUTBOUND: "沿离场航线飞离",
    DroneStatus.FINISHED: "已结束离场（机位已释放）",
}


class _MapOverlay(QWidget):
    """
    Overlay sitting on top of the map.
    It must NOT block map interactions except the zoom panel itself.
    """

    def __init__(self, map_canvas: MapCanvas, interactive_widgets: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._map = map_canvas
        self._interactive = interactive_widgets
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

    def _over_interactive(self, pos) -> bool:
        try:
            p = pos.toPoint()
        except AttributeError:
            p = pos
        return any(w.geometry().contains(p) for w in self._interactive)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._over_interactive(event.position()):
            forwarded = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                event.button(),
                event.buttons(),
                event.modifiers(),
            )
            self._map.mousePressEvent(forwarded)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._over_interactive(event.position()):
            forwarded = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                event.button(),
                event.buttons(),
                event.modifiers(),
            )
            self._map.mouseMoveEvent(forwarded)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._over_interactive(event.position()):
            forwarded = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                event.button(),
                event.buttons(),
                event.modifiers(),
            )
            self._map.mouseReleaseEvent(forwarded)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # Keep wheel-zoom on map unless the wheel is on zoom slider/panel.
        if not self._over_interactive(event.position()):
            self._map.wheelEvent(event)
            event.accept()
            return
        super().wheelEvent(event)


class _WeatherFetchThread(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, api_key: str, lat: float, lon: float, cache: WeatherCache, *, force_refresh: bool) -> None:
        super().__init__()
        self._api_key = api_key
        self._lat = lat
        self._lon = lon
        self._cache = cache
        self._force_refresh = force_refresh

    def run(self) -> None:  # noqa: N802
        try:
            data = self._cache.get(self._api_key, self._lat, self._lon, force_refresh=self._force_refresh)
            self.succeeded.emit(data)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(
        self,
        engine: SimulationEngine,
        waiting_zone: RectangleZone,
        pad_zone: RectangleZone,
        slots: List[Slot],
        obstacles: List[Obstacle],
        no_fly_zones: List[NoFlyZone],
        surveillance_radius: float,
        background_image: str | None,
        tick_seconds: float,
        gcs_config: Dict | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.tick_seconds = tick_seconds
        self._gcs: Dict = dict(gcs_config or {})
        self._weather_api_key = (
            (os.environ.get("WEATHERAPI_KEY") or self._gcs.get("weather_api_key") or "").strip()
        )
        self._weather_interval_s = float(self._gcs.get("weather_update_interval_seconds", 300.0))
        self._weather_cache = WeatherCache(self._weather_interval_s)
        self._weather_thread: _WeatherFetchThread | None = None
        self._gs_lat = float(self._gcs.get("default_lat", 29.52))
        self._gs_lon = float(self._gcs.get("default_lon", 106.56))
        self._location_name_override = (self._gcs.get("location_name_override") or "").strip()
        self._real_telemetry: Dict[str, dict] = {}
        self._last_adsb_snapshot: Dict[str, dict] = {}
        self._adsb_reader: ADSBSerialReader | None = None
        self._mav_workers: Dict[str, DroneTelemetryWorker] = {}
        self._mavlink_connected = False
        self._adsb_connected = False
        self.pad_zone = pad_zone
        self._real_drone_configs: List[Dict] = []
        self._drone_pilots: Dict[str, Dict[str, str]] = {}
        self._pilot_mailer = PilotMailer(self._gcs)
        self._pilot_deviation_alert_seen: Set[Tuple[str, float]] = set()
        self._drone_cards: Dict[str, GcsDroneInfoCard] = {}
        self._stand_cards: Dict[str, GcsStandInfoCard] = {}
        self._slot_placement_active = False
        self._sequential_demo_active = False
        self._demo_scenario_index = 0
        self._demo_sequence_timer = QTimer(self)
        self._demo_sequence_timer.setInterval(400)
        self._demo_sequence_timer.timeout.connect(self._tick_demo_sequence)
        # 演示批次首架机会写入该邮箱并尝试发送「机位分配」邮件（SMTP 见 config/demo_config.yaml gcs）
        self._demo_pilot_notify_email = "2076670913@qq.com"
        # 场景格式：(场景名, [(无人机ID, 机型, 尺寸, 功率, 电池容量, 优先级, 初始电量%)])
        self._demo_scenarios: List[Tuple[str, List[Tuple[str, str, float, float, float, int, float]]]] = [
            (
                "场景1：相同优先级-按停靠时长",
                [
                    ("DEMO-A1", "Model-A", 1.5, 8.0, 0.0, 0, 75.0),   # 优先级0，75%电量（中等停靠）
                    ("DEMO-A2", "Model-B", 1.5, 8.0, 0.0, 0, 30.0),   # 优先级0，30%电量（长停靠）
                    ("DEMO-A3", "Model-C", 1.5, 8.0, 0.0, 0, 90.0),   # 优先级0，90%电量（短停靠）
                ],
            ),
            (
                "场景2：不同优先级-高优先级优先",
                [
                    ("DEMO-B1", "Low-Pri", 1.5, 8.0, 0.0, 0, 50.0),    # 优先级0，50%电量
                    ("DEMO-B2", "Mid-Pri", 1.5, 8.0, 0.0, 5, 50.0),    # 优先级5，50%电量
                    ("DEMO-B3", "High-Pri", 1.5, 8.0, 0.0, 10, 50.0),  # 优先级10，50%电量
                ],
            ),
            (
                "场景3：Best-Fit尺寸匹配",
                [
                    ("DEMO-C1", "Small", 0.8, 5.0, 0.0, 0, 60.0),      # 小型机，应分配到小机位
                    ("DEMO-C2", "Medium", 1.8, 10.0, 0.0, 0, 60.0),    # 中型机，应分配到中机位
                    ("DEMO-C3", "Large", 3.2, 18.0, 0.0, 0, 60.0),     # 大型机，应分配到大机位
                ],
            ),
            (
                "场景4：功率不足-筛选失败",
                [
                    ("DEMO-D1", "Normal", 1.5, 8.0, 0.0, 0, 60.0),     # 正常功率需求
                    ("DEMO-D2", "HighPow", 1.5, 25.0, 0.0, 0, 60.0),   # 超高功率需求（可能无法满足）
                    ("DEMO-D3", "LowPow", 1.5, 3.0, 0.0, 0, 60.0),     # 低功率需求
                ],
            ),
            (
                "场景5：混合场景-综合测试",
                [
                    ("DEMO-E1", "VIP", 2.0, 12.0, 0.0, 15, 55.0),      # 高优先级15，中型，中功率
                    ("DEMO-E2", "Urgent", 1.2, 15.0, 0.0, 8, 40.0),    # 中优先级8，小型，高功率
                    ("DEMO-E3", "Normal", 2.5, 10.0, 0.0, 0, 70.0),    # 低优先级0，大型，中功率
                    ("DEMO-E4", "Quick", 0.9, 5.0, 0.0, 5, 85.0),      # 中优先级5，小型，低功率
                ],
            ),
            (
                "场景6：电量差异-停靠时长对比",
                [
                    ("DEMO-F1", "Full", 1.5, 8.0, 0.0, 0, 95.0),       # 优先级0，95%电量（短停靠）
                    ("DEMO-F2", "Half", 1.5, 8.0, 0.0, 0, 50.0),       # 优先级0，50%电量（中停靠）
                    ("DEMO-F3", "Low", 1.5, 8.0, 0.0, 0, 20.0),        # 优先级0，20%电量（长停靠）
                ],
            ),
        ]
        self._demo_live_scene_tag = ""
        self._demo_live_narrative_cache = ""
        self.setWindowTitle("无人机停靠算法 Demo")
        self.resize(1280, 820)

        self.map_canvas = MapCanvas(
            waiting_zone,
            pad_zone,
            slots,
            obstacles,
            no_fly_zones,
            surveillance_radius,
            safe_altitude_max=engine.safe_altitude_max,
            background_image=background_image,
        )
        self.map_canvas.set_geo_reference(self._gs_lat, self._gs_lon)

        self.status_table = QTableWidget(0, 7)
        self.status_table.setHorizontalHeaderLabels(
            ["Drone", "Status", "Slot", "Altitude", "Pos(x,y)", "纬度°", "经度°"]
        )
        self.alert_list = QListWidget()
        self.time_label = QLabel("System Time: t=0.0s")
        self.start_btn = QPushButton("开始")
        self.pause_btn = QPushButton("暂停")
        self.deviation_btn = QPushButton("偏航演示：脱离路径 / 恢复路径")
        self.assign_btn = QPushButton("机位分配并生成路径")

        self.id_input = QLineEdit("UAV-101")
        self.model_input = QLineEdit("M300")
        self.size_input = QLineEdit("1.2")
        self.power_input = QLineEdit("4.5")
        self.battery_kwh_input = QLineEdit("0")
        # 新增：电池电量百分比输入框，默认 50%
        self.battery_percent_input = QLineEdit("50")
        self.priority_input = QSpinBox()
        self.priority_input.setRange(1, 10)
        self.priority_input.setValue(5)
        self.assign_result = QLabel("分配结果: -")
        self.gps_label = QLabel("GPS: High")
        self.link_label = QLabel("Link: Good")
        self.power_label = QLabel("Power: 78%")
        self.alarm_label = QLabel("Active Alarms: 0")

        self.layer_base = QCheckBox("基础底图")
        self.layer_slots = QCheckBox("机位层")
        self.layer_obstacles = QCheckBox("障碍物层")
        self.layer_nofly = QCheckBox("禁飞区层")
        self.layer_routes = QCheckBox("路径规划层")
        self.label_altitude = QCheckBox("高度标签")
        for box in (self.layer_base, self.layer_slots, self.layer_obstacles, self.layer_nofly, self.layer_routes):
            box.setChecked(True)
        self.label_altitude.setChecked(True)

        # --- Sidebar (icon rail + stacked content, like reference UI) ---
        sidebar_root = QHBoxLayout()
        sidebar_root.setContentsMargins(0, 0, 0, 0)
        sidebar_root.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("sideRail")
        rail.setFixedWidth(56)
        rail_layout = QVBoxLayout()
        rail_layout.setContentsMargins(6, 10, 6, 10)
        rail_layout.setSpacing(8)

        self.nav_layers = QToolButton()
        self.nav_layers.setObjectName("navBtn")
        self.nav_layers.setCheckable(True)
        self.nav_layers.setChecked(True)
        self.nav_layers.setToolTip("图层")
        self.nav_layers.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))

        self.nav_stands = QToolButton()
        self.nav_stands.setObjectName("navBtn")
        self.nav_stands.setCheckable(True)
        self.nav_stands.setToolTip("机位管理")
        self.nav_stands.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))

        self.nav_control = QToolButton()
        self.nav_control.setObjectName("navBtn")
        self.nav_control.setCheckable(True)
        self.nav_control.setToolTip("控制")
        self.nav_control.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

        self.nav_mission = QToolButton()
        self.nav_mission.setObjectName("navBtn")
        self.nav_mission.setCheckable(True)
        self.nav_mission.setToolTip("任务")
        self.nav_mission.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))

        self.nav_uav = QToolButton()
        self.nav_uav.setObjectName("navBtn")
        self.nav_uav.setCheckable(True)
        self.nav_uav.setToolTip("无人机信息")
        self.nav_uav.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView))

        self.nav_comm = QToolButton()
        self.nav_comm.setObjectName("navBtn")
        self.nav_comm.setCheckable(True)
        self.nav_comm.setToolTip("地面站 / 无人机经纬度 / 雷达列表 / 天气")
        self.nav_comm.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))

        self.nav_status = QToolButton()
        self.nav_status.setObjectName("navBtn")
        self.nav_status.setCheckable(True)
        self.nav_status.setToolTip("状态")
        self.nav_status.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))

        for btn in (
            self.nav_layers,
            self.nav_stands,
            self.nav_control,
            self.nav_mission,
            self.nav_uav,
            self.nav_comm,
            self.nav_status,
        ):
            btn.setIconSize(QSize(22, 22))
            btn.setAutoRaise(True)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            rail_layout.addWidget(btn)

        rail_layout.addStretch(1)
        rail.setLayout(rail_layout)

        content = QFrame()
        content.setObjectName("sideContent")
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        side_title = QLabel("地图图层")
        side_title.setObjectName("sideTitle")
        content_layout.addWidget(side_title)

        self.side_stack = QStackedWidget()
        self.side_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Layers page: tree with toggle switches
        layers_page = QWidget()
        layers_layout = QVBoxLayout()
        layers_layout.setContentsMargins(8, 8, 8, 8)
        layers_layout.setSpacing(8)
        layers_tree = QTreeWidget()
        layers_tree.setHeaderHidden(True)
        layers_tree.setIndentation(14)
        layers_tree.setRootIsDecorated(False)
        layers_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layers_tree.setTextElideMode(Qt.ElideRight)

        def _add_switch_item(parent: QTreeWidgetItem, title: str, checkbox: QCheckBox) -> None:
            item = QTreeWidgetItem(parent, [title])
            layers_tree.setItemWidget(item, 1, checkbox)

        # Use 2 columns: title + switch widget
        layers_tree.setColumnCount(2)
        header = layers_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        root_layers = QTreeWidgetItem(layers_tree, ["地图图层"])
        root_layers.setExpanded(True)
        _add_switch_item(root_layers, "基础底图", self.layer_base)
        _add_switch_item(root_layers, "机位层", self.layer_slots)
        _add_switch_item(root_layers, "障碍物层", self.layer_obstacles)
        _add_switch_item(root_layers, "禁飞区层", self.layer_nofly)
        _add_switch_item(root_layers, "路径规划层", self.layer_routes)
        _add_switch_item(root_layers, "高度标签", self.label_altitude)
        layers_layout.addWidget(layers_tree, 1)
        layers_page.setLayout(layers_layout)

        # Control page
        control_page = QWidget()
        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(8)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.deviation_btn)
        demo_l = QLabel(
            "「开始」将按顺序自动演示6个场景：相同优先级 → 不同优先级 → Best-Fit → 功率筛选 → 混合 → 电量差异；每段结束后清空再开始下一段。"
            "点某一演示按钮会先清空再只跑该场景，并自动启动仿真。"
        )
        demo_l.setWordWrap(True)
        demo_l.setObjectName("gcsMonoHint")
        control_layout.addWidget(demo_l)
        self.btn_demo_sizes = QPushButton("场景1：相同优先级")
        self.btn_demo_power = QPushButton("场景2：不同优先级")
        self.btn_demo_mixed = QPushButton("场景3：Best-Fit")
        self.btn_demo_power_filter = QPushButton("场景4：功率筛选")
        self.btn_demo_comprehensive = QPushButton("场景5：综合测试")
        self.btn_demo_battery = QPushButton("场景6：电量差异")
        self.btn_demo_sizes.clicked.connect(self._on_demo_size_batch)
        self.btn_demo_power.clicked.connect(self._on_demo_power_batch)
        self.btn_demo_mixed.clicked.connect(self._on_demo_mixed_batch)
        self.btn_demo_power_filter.clicked.connect(self._on_demo_power_filter_batch)
        self.btn_demo_comprehensive.clicked.connect(self._on_demo_comprehensive_batch)
        self.btn_demo_battery.clicked.connect(self._on_demo_battery_batch)
        control_layout.addWidget(self.btn_demo_sizes)
        control_layout.addWidget(self.btn_demo_power)
        control_layout.addWidget(self.btn_demo_mixed)
        control_layout.addWidget(self.btn_demo_power_filter)
        control_layout.addWidget(self.btn_demo_comprehensive)
        control_layout.addWidget(self.btn_demo_battery)

        demo_live_title = QLabel("演示实况（随仿真刷新）")
        demo_live_title.setWordWrap(True)
        demo_live_title.setStyleSheet("font-weight: 700; color: #0c1929; font-size: 12px;")
        control_layout.addWidget(demo_live_title)

        # 仅用 QTextEdit 自带竖条滚动；外包 QScrollArea + 自适应高度会导致每次刷新重置外层滑条、无法拖动。
        self._demo_live_feed = QTextEdit()
        self._demo_live_feed.setReadOnly(True)
        self._demo_live_feed.setFrameShape(QFrame.NoFrame)
        self._demo_live_feed.setPlaceholderText("开始演示或添加任务机后，此处显示实时状态与分配说明…")
        self._demo_live_feed.setObjectName("gcsMonoHint")
        self._demo_live_feed.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._demo_live_feed.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._demo_live_feed.setMinimumHeight(220)
        self._demo_live_feed.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        control_layout.addWidget(self._demo_live_feed, 1)

        control_page.setLayout(control_layout)

        # Mission page (assignment)
        mission_page = QWidget()
        mission_layout = QVBoxLayout()
        mission_layout.setContentsMargins(8, 8, 8, 8)
        mission_layout.setSpacing(8)
        form = QFormLayout()
        form.addRow("无人机ID", self.id_input)
        form.addRow("机型", self.model_input)
        form.addRow("尺寸", self.size_input)
        form.addRow("充电功率(kW)", self.power_input)
        form.addRow("电池容量(kWh,0=自动)", self.battery_kwh_input)
        # 新增：电池电量百分比输入行，用于指定无人机当前电量（0-100%）
        form.addRow("电池电量(%)", self.battery_percent_input)
        form.addRow("优先级", self.priority_input)
        mission_layout.addLayout(form)
        mission_layout.addWidget(self.assign_btn)
        mission_layout.addWidget(self.assign_result)
        mission_layout.addStretch(1)
        mission_page.setLayout(mission_layout)

        # UAV info page：无人机卡（仿真 / 实机），连接与分配在卡面上操作
        uav_page = QWidget()
        uav_outer = QVBoxLayout(uav_page)
        uav_outer.setContentsMargins(8, 8, 8, 8)
        uav_outer.setSpacing(8)
        uav_hint = QLabel(
            "每张卡显示经纬度、高度、电量、充电功率(W)、卫星与 MAVLink；实机填写连接后点「连接」，"
            "或用「⚙ MAVLink」改串口。仿真机带模拟电量/停靠充电功率。"
            "分配机位后可邮件通知飞手：在 config/demo_config.yaml 的 gcs 中配置 pilot_smtp_*，"
            "授权码用环境变量 PILOT_SMTP_PASSWORD（勿写入 YAML）；演示批次首架机默认飞手邮箱 2076670913@qq.com。"
        )
        uav_hint.setWordWrap(True)
        uav_hint.setObjectName("gcsMonoHint")
        uav_outer.addWidget(uav_hint)
        uav_btn_row = QHBoxLayout()
        self.btn_add_real_drone = QPushButton("+ 添加实机")
        self.btn_add_real_drone.clicked.connect(self._on_add_real_drone)
        uav_btn_row.addWidget(self.btn_add_real_drone)
        uav_btn_row.addStretch(1)
        uav_outer.addLayout(uav_btn_row)
        uav_scroll = QScrollArea()
        uav_scroll.setWidgetResizable(True)
        uav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        uav_scroll.setFrameShape(QFrame.NoFrame)
        uav_inner = QWidget()
        self._uav_cards_layout = QVBoxLayout(uav_inner)
        self._uav_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._uav_cards_layout.setSpacing(8)
        uav_scroll.setWidget(uav_inner)
        uav_outer.addWidget(uav_scroll, 1)

        # 机位管理页（卡面 + 地图点选添加，仅限停机坪区域）
        stands_page = QWidget()
        stands_outer = QVBoxLayout(stands_page)
        stands_outer.setContentsMargins(8, 8, 8, 8)
        stands_outer.setSpacing(8)
        stands_hint = QLabel(
            "机位状态：空闲 / 已占用。地图选点添加（须在绿色停机坪内）：填写保护区半径、最大机型尺寸、充电功率；"
            "若与已有机位圆形保护区重叠将无法保存。"
        )
        stands_hint.setWordWrap(True)
        stands_hint.setObjectName("gcsMonoHint")
        stands_outer.addWidget(stands_hint)
        st_btn_row = QHBoxLayout()
        self.btn_slot_pick_map = QPushButton("在地图上点选添加机位")
        self.btn_slot_pick_map.setCheckable(True)
        self.btn_slot_pick_map.toggled.connect(self._on_toggle_slot_placement_mode)
        st_btn_row.addWidget(self.btn_slot_pick_map)
        st_btn_row.addStretch(1)
        stands_outer.addLayout(st_btn_row)
        stands_scroll = QScrollArea()
        stands_scroll.setWidgetResizable(True)
        stands_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        stands_scroll.setFrameShape(QFrame.NoFrame)
        stands_inner = QWidget()
        self._stand_cards_layout = QVBoxLayout(stands_inner)
        self._stand_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._stand_cards_layout.setSpacing(8)
        stands_scroll.setWidget(stands_inner)
        stands_outer.addWidget(stands_scroll, 1)

        # Communication page：地面站位置、无人机 WGS84、雷达目标列表、天气刷新
        comm_page = QWidget()
        comm_outer = QVBoxLayout(comm_page)
        comm_outer.setContentsMargins(0, 0, 0, 0)
        comm_scroll = QScrollArea()
        comm_scroll.setWidgetResizable(True)
        comm_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        comm_inner = QWidget()
        comm_layout = QVBoxLayout(comm_inner)
        comm_layout.setContentsMargins(6, 6, 6, 6)
        comm_layout.setSpacing(4)

        comm_layout.addWidget(QLabel("地面站 WGS84（与地图原点对齐）"))
        self.comm_station_label = QLabel(
            f"纬度 {self._gs_lat:.6f}\n经度 {self._gs_lon:.6f}\n来源: 配置默认值"
        )
        self.comm_station_label.setWordWrap(True)
        self.comm_station_label.setObjectName("gcsMonoHint")
        self.comm_station_label.setMaximumHeight(45)
        comm_layout.addWidget(self.comm_station_label)

        loc_row = QHBoxLayout()
        self.btn_refresh_location = QPushButton("刷新位置 (GNSS→Win→默认)")
        self.btn_refresh_location.clicked.connect(self._on_refresh_ground_station_location)
        loc_row.addWidget(self.btn_refresh_location)
        comm_layout.addLayout(loc_row)

        comm_layout.addWidget(QLabel("天气"))
        self.comm_weather_hint = QLabel(
            "使用 WeatherAPI.com；在 config/demo_config.yaml 填写 gcs.weather_api_key"
        )
        self.comm_weather_hint.setWordWrap(True)
        self.comm_weather_hint.setObjectName("gcsMonoHint")
        self.comm_weather_hint.setMaximumHeight(35)
        comm_layout.addWidget(self.comm_weather_hint)
        self.btn_refresh_weather = QPushButton("刷新天气")
        self.btn_refresh_weather.clicked.connect(lambda: self._start_weather_fetch(force_refresh=True))
        comm_layout.addWidget(self.btn_refresh_weather)

        comm_layout.addWidget(QLabel("串口快捷选择"))
        serial_row = QHBoxLayout()
        self.serial_ports_combo = QComboBox()
        self.serial_ports_combo.setMinimumWidth(200)
        serial_row.addWidget(self.serial_ports_combo, 1)
        self.btn_refresh_serial_ports = QPushButton("刷新串口")
        self.btn_refresh_serial_ports.setToolTip("枚举本机串口（需安装 pyserial）")
        self.btn_refresh_serial_ports.clicked.connect(self._refresh_serial_ports_combo)
        serial_row.addWidget(self.btn_refresh_serial_ports)
        btn_pick_m = QPushButton("→ MAVLink")
        btn_pick_m.setToolTip("将当前下拉项填入 MAVLink 连接")
        btn_pick_m.clicked.connect(self._copy_serial_pick_to_mavlink_edit)
        serial_row.addWidget(btn_pick_m)
        btn_pick_a = QPushButton("→ ADS-B")
        btn_pick_a.setToolTip("将当前下拉项填入 ADS-B 串口")
        btn_pick_a.clicked.connect(self._copy_serial_pick_to_adsb_edit)
        serial_row.addWidget(btn_pick_a)
        comm_layout.addLayout(serial_row)

        comm_layout.addWidget(QLabel("MAVLink / 无人机"))
        ml_form = QFormLayout()
        self.edit_mavlink_uri = QLineEdit()
        self.edit_mavlink_uri.setPlaceholderText("COM15、/dev/ttyUSB0、udp:127.0.0.1:14550 …")
        self.edit_mavlink_uri.setText((self._gcs.get("mavlink_connection") or "").strip())
        ml_form.addRow("连接", self.edit_mavlink_uri)
        self.spin_mavlink_baud = QSpinBox()
        self.spin_mavlink_baud.setRange(1200, 921600)
        self.spin_mavlink_baud.setSingleStep(1200)
        self.spin_mavlink_baud.setValue(int(self._gcs.get("mavlink_baud", 57600)))
        ml_form.addRow("波特率", self.spin_mavlink_baud)
        self.edit_mavlink_drone_id = QLineEdit(str(self._gcs.get("mavlink_drone_id", "REAL-1")))
        ml_form.addRow("遥测 ID", self.edit_mavlink_drone_id)
        self.edit_mavlink_drone_name = QLineEdit(str(self._gcs.get("mavlink_drone_name", "实机")))
        ml_form.addRow("显示名称", self.edit_mavlink_drone_name)
        comm_layout.addLayout(ml_form)
        self.btn_apply_mavlink = QPushButton("应用 MAVLink")
        self.btn_apply_mavlink.clicked.connect(self._apply_mavlink_settings_from_ui)
        comm_layout.addWidget(self.btn_apply_mavlink)

        self.lbl_mavlink = QLabel("")
        self.lbl_mavlink.setWordWrap(True)
        self.lbl_mavlink.setObjectName("gcsMonoHint")
        comm_layout.addWidget(self.lbl_mavlink)
        ml_row = QHBoxLayout()
        self.btn_mavlink = QPushButton("连接实机")
        self.btn_mavlink.clicked.connect(self._toggle_mavlink)
        ml_row.addWidget(self.btn_mavlink)
        comm_layout.addLayout(ml_row)

        comm_layout.addWidget(QLabel("ADS-B 接收机"))
        ad_form = QFormLayout()
        self.edit_adsb_port = QLineEdit()
        self.edit_adsb_port.setPlaceholderText("例如 COM6")
        self.edit_adsb_port.setText((self._gcs.get("adsb_serial_port") or "").strip())
        ad_form.addRow("串口", self.edit_adsb_port)
        self.spin_adsb_baud = QSpinBox()
        self.spin_adsb_baud.setRange(9600, 921600)
        self.spin_adsb_baud.setSingleStep(1200)
        self.spin_adsb_baud.setValue(int(self._gcs.get("adsb_serial_baud", 921600)))
        ad_form.addRow("波特率", self.spin_adsb_baud)
        comm_layout.addLayout(ad_form)
        self.btn_apply_adsb = QPushButton("应用 ADS-B")
        self.btn_apply_adsb.clicked.connect(self._apply_adsb_settings_from_ui)
        comm_layout.addWidget(self.btn_apply_adsb)

        self.lbl_adsb = QLabel("")
        self.lbl_adsb.setWordWrap(True)
        self.lbl_adsb.setObjectName("gcsMonoHint")
        comm_layout.addWidget(self.lbl_adsb)
        ad_row = QHBoxLayout()
        self.btn_adsb = QPushButton("连接 ADS-B")
        self.btn_adsb.clicked.connect(self._toggle_adsb)
        ad_row.addWidget(self.btn_adsb)
        comm_layout.addLayout(ad_row)

        comm_layout.addWidget(QLabel("无人机 WGS84（地面站 + 仿真坐标推算）"))
        self.comm_drone_table = QTableWidget(0, 5)
        self.comm_drone_table.setHorizontalHeaderLabels(["ID", "纬度°", "经度°", "高度 m", "地速 m/s"])
        self.comm_drone_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.comm_drone_table.setMinimumHeight(90)
        self.comm_drone_table.setMaximumHeight(130)
        comm_layout.addWidget(self.comm_drone_table)

        comm_layout.addWidget(QLabel("雷达目标（实机 / ADS-B / 仿真）"))
        self.comm_radar_log = QTextEdit()
        self.comm_radar_log.setReadOnly(True)
        self.comm_radar_log.setPlaceholderText("目标列表…")
        self.comm_radar_log.setMinimumHeight(70)
        self.comm_radar_log.setMaximumHeight(110)
        comm_layout.addWidget(self.comm_radar_log)

        comm_layout.addStretch(1)
        comm_scroll.setWidget(comm_inner)
        comm_outer.addWidget(comm_scroll)

        # Status/log page
        status_page = QWidget()
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(8, 8, 8, 8)
        status_layout.setSpacing(8)
        status_layout.addWidget(QLabel("无人机状态"))
        status_layout.addWidget(self.status_table, 1)
        status_layout.addWidget(QLabel("告警与邮件日志"))
        status_layout.addWidget(self.alert_list, 1)
        status_page.setLayout(status_layout)

        self.side_stack.addWidget(layers_page)   # 0
        self.side_stack.addWidget(stands_page)   # 1
        self.side_stack.addWidget(control_page)  # 2
        self.side_stack.addWidget(mission_page)  # 3
        self.side_stack.addWidget(uav_page)      # 4
        self.side_stack.addWidget(comm_page)     # 5
        self.side_stack.addWidget(status_page)   # 6

        content_layout.addWidget(self.side_stack, 1)
        content.setLayout(content_layout)

        sidebar_root.addWidget(rail)
        sidebar_root.addWidget(content, 1)

        side_widget = QWidget()
        side_widget.setLayout(sidebar_root)
        side_widget.setMinimumWidth(550)

        top_bar = QWidget()
        top_bar.setObjectName("topStatusStrip")
        top_strip = QHBoxLayout(top_bar)
        top_strip.setContentsMargins(14, 10, 14, 10)
        top_strip.setSpacing(16)
        top_strip.addWidget(QLabel("GCS UAV Map"))
        top_strip.addStretch(1)
        top_strip.addWidget(self.gps_label)
        top_strip.addWidget(self.link_label)
        top_strip.addWidget(self.power_label)
        top_strip.addWidget(self.time_label)
        top_strip.addWidget(self.alarm_label)

        # --- Map overlay controls (zoom +/- buttons, slider, zoom level label) ---
        map_container = QWidget()
        map_container.setObjectName("mapShell")
        map_stack = QStackedLayout()
        map_stack.setStackingMode(QStackedLayout.StackAll)
        map_stack.setContentsMargins(0, 0, 0, 0)

        overlay_layout = QHBoxLayout()
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        overlay_layout.addStretch(1)

        right_tools = QFrame()
        right_tools.setObjectName("rightTools")
        tools_layout = QVBoxLayout()
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(8)

        # Tool column (match reference vertical bar)
        self.btn_fit = QToolButton()
        self.btn_fit.setObjectName("toolBtn")
        self.btn_fit.setToolTip("适配全图")
        self.btn_fit.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarShadeButton))

        self.btn_center = QToolButton()
        self.btn_center.setObjectName("toolBtn")
        self.btn_center.setToolTip("定位中心(0,0)")
        self.btn_center.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))

        self.btn_reset = QToolButton()
        self.btn_reset.setObjectName("toolBtn")
        self.btn_reset.setToolTip("复位视角")
        self.btn_reset.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))

        self.btn_measure = QToolButton()
        self.btn_measure.setObjectName("toolBtn")
        self.btn_measure.setToolTip("测距(开发中)")
        self.btn_measure.setCheckable(True)
        self.btn_measure.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogHelpButton))

        self.btn_fullscreen = QToolButton()
        self.btn_fullscreen.setObjectName("toolBtn")
        self.btn_fullscreen.setToolTip("全屏")
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))

        for b in (self.btn_fit, self.btn_center, self.btn_reset, self.btn_measure, self.btn_fullscreen):
            b.setAutoRaise(True)
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(32, 32)
            tools_layout.addWidget(b)

        tools_layout.addStretch(1)

        # Slim zoom slider only (no panel frame)
        self.zoom_slider = QSlider(Qt.Vertical)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFixedSize(14, 160)
        tools_layout.addWidget(self.zoom_slider, 0, Qt.AlignHCenter)
        tools_layout.addSpacing(8)

        right_tools.setLayout(tools_layout)
        overlay_layout.addWidget(right_tools)

        overlay = _MapOverlay(self.map_canvas, [right_tools, self.zoom_slider])
        overlay.setStyleSheet("background: transparent;")
        overlay.setLayout(overlay_layout)

        map_stack.addWidget(self.map_canvas)
        map_stack.addWidget(overlay)
        map_container.setLayout(map_stack)

        # 底部：ADS-B雷达 + 天气信息（横向排列）
        self.bottom_panel = QWidget()
        self.bottom_panel.setObjectName("bottomDock")
        self.bottom_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_panel.setFixedHeight(228)
        bottom_row = QHBoxLayout(self.bottom_panel)
        bottom_row.setSpacing(8)
        bottom_row.setContentsMargins(0, 8, 0, 0)

        # ADS-B雷达
        radar_panel = QFrame()
        radar_panel.setObjectName("gcsBottomRadar")
        radar_panel.setFrameShape(QFrame.StyledPanel)
        radar_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        radar_panel.setFixedHeight(220)
        radar_v = QVBoxLayout(radar_panel)
        radar_v.setContentsMargins(10, 8, 10, 8)
        radar_v.setSpacing(4)
        self.bottom_radar_title = QLabel("ADS-B 50.0 km")
        self.bottom_radar_title.setObjectName("gcsRadarTitle")
        radar_v.addWidget(self.bottom_radar_title, 0)
        self.bottom_radar = RadarWidget()
        self.bottom_radar.setFixedHeight(180)
        self.bottom_radar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_radar.set_center(self._gs_lat, self._gs_lon)
        radar_v.addWidget(self.bottom_radar, 0)
        bottom_row.addWidget(radar_panel, 1)

        # 天气信息
        self.bottom_weather = GcsWeatherCard()
        self.bottom_weather.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_weather.setFixedHeight(220)
        self.bottom_weather.update_station_info(self._gs_lat, self._gs_lon)
        bottom_row.addWidget(self.bottom_weather, 1)

        # 传感器数据
        self.bottom_sensor = GcsSensorCard()
        self.bottom_sensor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_sensor.setFixedHeight(220)
        bottom_row.addWidget(self.bottom_sensor, 1)

        # 左侧面板：仅地图
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(map_container)

        # 主分割器：左侧面板 + 右侧边栏
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(side_widget)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([920, 550])
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)

        self._radar_title_timer = QTimer(self)
        self._radar_title_timer.timeout.connect(self._refresh_bottom_radar_title)
        self._radar_title_timer.start(500)

        self._weather_timer = QTimer(self)
        self._weather_timer.timeout.connect(lambda: self._start_weather_fetch(force_refresh=False))
        self._weather_timer.setInterval(int(max(60.0, self._weather_interval_s) * 1000))

        self._peripheral_timer = QTimer(self)
        self._peripheral_timer.timeout.connect(self._refresh_peripherals_ui)
        self._peripheral_timer.start(400)

        container = QWidget()
        container.setObjectName("mainShell")
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(top_bar)
        root.addWidget(splitter, 1)
        root.addWidget(self.bottom_panel)
        container.setLayout(root)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.setInterval(max(1, int(tick_seconds * 1000)))
        self.timer.timeout.connect(self._tick)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.pause_btn.clicked.connect(self.timer.stop)
        self.deviation_btn.clicked.connect(self._inject_deviation)
        self.assign_btn.clicked.connect(self._assign_drone)
        self.layer_base.toggled.connect(lambda v: self.map_canvas.set_layer_visible("base", v))
        self.layer_slots.toggled.connect(lambda v: self.map_canvas.set_layer_visible("slots", v))
        self.layer_obstacles.toggled.connect(lambda v: self.map_canvas.set_layer_visible("obstacles", v))
        self.layer_nofly.toggled.connect(lambda v: self.map_canvas.set_layer_visible("no_fly", v))
        self.layer_routes.toggled.connect(lambda v: self.map_canvas.set_layer_visible("routes", v))
        self.label_altitude.toggled.connect(self.map_canvas.set_show_altitude_labels)
        self._wire_zoom_controls()
        self._wire_sidebar_nav(side_title)
        self._wire_map_tools()
        self._apply_gcs_style()
        self.map_canvas.fit_to_content()
        self.map_canvas.slot_placement_chosen.connect(self._on_map_slot_place_chosen)
        self._seed_real_configs_from_gcs()
        self._rebuild_stand_cards()
        self._rebuild_drone_cards()
        QTimer.singleShot(400, self._bootstrap_location_and_weather)
        self._refresh_gcs_panels_from_snapshot()
        self._init_mavlink_and_adsb_ui()
        self._init_hardware_workers()
        self._sync_drone_cards_telemetry()
        QTimer.singleShot(150, self._refresh_serial_ports_combo)

    @property
    def drone_pilots(self) -> Dict[str, Dict[str, str]]:
        return self._drone_pilots

    @property
    def drone_cards(self) -> Dict[str, GcsDroneInfoCard]:
        return self._drone_cards

    def _default_sim_pilot(self, drone_id: str) -> Dict[str, str]:
        h = abs(hash(drone_id)) % 1000
        return {"name": f"仿真飞手{h:03d}", "email": "", "phone": ""}

    def _notify_pilot_if_drone_has_assigned_slot(self, drone_id: str) -> None:
        """任务页等路径在引擎中完成机位预约后，与卡片手动分配一致地尝试通知飞手。"""
        d = next((x for x in self.engine.drones if x.drone_id == drone_id), None)
        if not d or not d.assigned_slot_id:
            return
        slot = next((s for s in self.engine.slots if s.slot_id == d.assigned_slot_id), None)
        if not slot:
            return
        self._maybe_email_pilot_stand_assigned(drone_id, self._stand_info_dict(slot))

    def _seed_demo_pilot_for_notify_email(self, drone_id: str) -> None:
        """演示批次：为首架成功入队的飞机写入飞手邮箱，便于联调 SMTP。"""
        em = (getattr(self, "_demo_pilot_notify_email", None) or "").strip()
        if not em:
            return
        base = self._drone_pilots.get(drone_id) or self._default_sim_pilot(drone_id)
        self._drone_pilots[drone_id] = {**base, "name": base.get("name") or "演示飞手", "email": em}

    def _maybe_email_pilot_stand_assigned(self, drone_id: str, stand_info: dict) -> None:
        if not self._pilot_mailer.is_enabled():
            return
        pilot = self._drone_pilots.get(str(drone_id), {})
        to_email = (pilot.get("email") or "").strip()
        if not to_email:
            self.statusBar().showMessage(f"✉️ 跳过邮件：无人机 {drone_id} 未设置飞手邮箱", 6000)
            return
        card = self._drone_cards.get(str(drone_id))
        drone_name = card.drone_name if card else f"无人机 {drone_id}"
        stand_name = stand_info.get("name", stand_info.get("id", "--"))
        stand_type = "室内" if stand_info.get("type") == "indoor" else "室外"
        assigned_time = stand_info.get("assigned_time", "--")
        subject = f"【机位分配通知】{drone_name} 已分配至 {stand_name}"
        body = f"""
        <div style="font-family:'Microsoft YaHei',Arial,sans-serif;font-size:14px;color:#303133;">
            <h3 style="margin:0 0 10px 0;color:#409EFF;">机位分配成功</h3>
            <p>您好，{pilot.get('name', '飞手')}：</p>
            <p>无人机 <b>{drone_name}</b> 已成功分配到机位 <b>{stand_name}</b>（{stand_type}）。</p>
            <ul style="line-height:1.8;">
                <li>机位名称：{stand_name}</li>
                <li>类型：{stand_type}</li>
                <li>分配时间：{assigned_time}</li>
            </ul>
            <p style="color:#909399;">此邮件由系统自动发送，请勿直接回复。</p>
        </div>
        """
        ok, detail = self._pilot_mailer.send_html([to_email], subject, body)
        self.statusBar().showMessage(("✉️ " + detail) if ok else ("✉️ 邮件失败： " + detail), 8000)

    def _maybe_email_pilot_deviation(self, drone_id: str, alert_message: str) -> None:
        if not self._pilot_mailer.is_enabled():
            return
        pilot = self._drone_pilots.get(str(drone_id), {})
        to_email = (pilot.get("email") or "").strip()
        if not to_email:
            self.statusBar().showMessage(f"✉️ 偏航通知跳过：{drone_id} 无飞手邮箱", 5000)
            return
        card = self._drone_cards.get(str(drone_id))
        drone_name = card.drone_name if card else f"无人机 {drone_id}"
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"【偏航告警】{drone_name}（{drone_id}）"
        body = f"""
        <div style="font-family:'Microsoft YaHei',Arial,sans-serif;font-size:14px;color:#303133;">
            <h3 style="margin:0 0 10px 0;color:#E6A23C;">路径偏航告警</h3>
            <p>您好，{pilot.get('name', '飞手')}：</p>
            <p>无人机 <b>{drone_name}</b> 报告与规划路径持续偏离，请关注姿态与遥控链路。</p>
            <p style="background:#fdf6ec;padding:8px;border-radius:6px;">系统记录：{alert_message}</p>
            <p style="color:#909399;">通知时间：{t}<br/>此邮件由系统自动发送。</p>
        </div>
        """
        ok, detail = self._pilot_mailer.send_html([to_email], subject, body)
        self.statusBar().showMessage(("✉️ 偏航通知：" + detail) if ok else ("✉️ 偏航邮件失败：" + detail), 8000)

    def _process_pilot_deviation_alerts(self) -> None:
        for rec in self.engine.alert_service.records:
            key = (rec.drone_id, round(float(rec.timestamp), 2))
            if key in self._pilot_deviation_alert_seen:
                continue
            if "deviation" not in (rec.message or "").lower():
                continue
            self._pilot_deviation_alert_seen.add(key)
            self._maybe_email_pilot_deviation(rec.drone_id, rec.message)
        if len(self._pilot_deviation_alert_seen) > 400:
            self._pilot_deviation_alert_seen = set(list(self._pilot_deviation_alert_seen)[-200:])

    def _wire_map_tools(self) -> None:
        self.btn_center.clicked.connect(self.map_canvas.center_on_origin)
        self.btn_reset.clicked.connect(self.map_canvas.reset_view)
        self.btn_fit.clicked.connect(self.map_canvas.fit_to_content)
        self.btn_fullscreen.toggled.connect(self._toggle_fullscreen)

    def _wire_sidebar_nav(self, side_title: QLabel) -> None:
        buttons = [
            self.nav_layers,
            self.nav_stands,
            self.nav_control,
            self.nav_mission,
            self.nav_uav,
            self.nav_comm,
            self.nav_status,
        ]
        titles = [
            "地图图层",
            "机位管理",
            "控制",
            "任务",
            "无人机信息",
            "地面站·雷达·天气",
            "状态",
        ]

        def activate(idx: int) -> None:
            for i, b in enumerate(buttons):
                b.blockSignals(True)
                b.setChecked(i == idx)
                b.blockSignals(False)
            self.side_stack.setCurrentIndex(idx)
            side_title.setText(titles[idx])

        self.nav_layers.clicked.connect(lambda: activate(0))
        self.nav_stands.clicked.connect(lambda: activate(1))
        self.nav_control.clicked.connect(lambda: activate(2))
        self.nav_mission.clicked.connect(lambda: activate(3))
        self.nav_uav.clicked.connect(lambda: activate(4))
        self.nav_comm.clicked.connect(lambda: activate(5))
        self.nav_status.clicked.connect(lambda: activate(6))
        activate(0)

    def _wire_zoom_controls(self) -> None:
        # Map scale -> slider (log-like feel, stable mapping)
        def scale_to_slider(scale: float) -> int:
            t = (scale - self.map_canvas.min_scale) / (self.map_canvas.max_scale - self.map_canvas.min_scale)
            return int(max(0.0, min(1.0, t)) * 1000)

        def slider_to_scale(v: int) -> float:
            t = max(0.0, min(1.0, v / 1000.0))
            return self.map_canvas.min_scale + t * (self.map_canvas.max_scale - self.map_canvas.min_scale)

        self.zoom_slider.setValue(scale_to_slider(self.map_canvas.scale))

        def _on_map_scale_changed(s: float) -> None:
            # 用户拖动缩放滑条时不要被 scale_changed 回写打断
            if self.zoom_slider.isSliderDown():
                return
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(scale_to_slider(s))
            self.zoom_slider.blockSignals(False)

        self.map_canvas.scale_changed.connect(_on_map_scale_changed)

        self.zoom_slider.valueChanged.connect(lambda v: self.map_canvas.set_scale(slider_to_scale(v)))

    def _apply_gcs_style(self) -> None:
        self.setStyleSheet(
            """
            /* 明/暗交错：顶栏、底栏、侧栏轨、地图浮层为深色；工作区与表单偏亮 */
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a2332, stop:0.4 #2d3b4e, stop:1 #1f2937);
                font-family: "Times New Roman", "SimSun", "Microsoft YaHei", serif;
                font-size: 12px;
                color: #0f172a;
            }
            QWidget {
                font-family: "Times New Roman", "SimSun", "Microsoft YaHei", serif;
                font-size: 12px;
                color: #0f172a;
            }
            QWidget#topStatusStrip {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #334155, stop:0.55 #1e293b, stop:1 #0f172a);
                border-bottom: 2px solid #020617;
            }
            QWidget#topStatusStrip QLabel {
                color: #e2e8f0;
                font-weight: 600;
            }
            QWidget#mainShell, QWidget#mapShell {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d3b4e, stop:0.4 #1f2937, stop:1 #1a2332);
            }
            QWidget#bottomDock {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f172a, stop:0.45 #1e293b, stop:1 #334155);
                border-top: 2px solid #020617;
            }
            QSplitter::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #475569, stop:0.5 #334155, stop:1 #1e293b);
                width: 6px;
                border-left: 1px solid #64748b;
                border-right: 1px solid #020617;
            }
            QLabel { color: #1e293b; }
            QLabel#sideTitle {
                font-size: 15px;
                font-weight: 700;
                color: #0c1929;
                letter-spacing: 0.5px;
                padding: 4px 0 10px 0;
                border-bottom: 2px solid #9eb4d4;
                margin-bottom: 4px;
            }

            QLineEdit, QSpinBox, QComboBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #feffff, stop:1 #e3edf8);
                color: #0f172a;
                border: 1px solid #8fa3c4;
                border-radius: 9px;
                padding: 7px 10px;
                min-height: 20px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 2px solid #2563eb;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f0f7ff, stop:1 #e8f4ff);
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8fbff, stop:1 #dce8f4);
                color: #0f172a;
                selection-background-color: #bfdbfe;
                selection-color: #0f172a;
                border: 1px solid #8fa3c4;
            }

            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f8faff, stop:0.5 #e8f0fa, stop:1 #d4e2f2);
                border: 1px solid #7f96bd;
                border-radius: 10px;
                color: #0f172a;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #eff6ff, stop:1 #dbeafe);
                border: 1px solid #3b82f6;
                color: #1d4ed8;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #bfdbfe, stop:1 #93c5fd);
                border: 1px solid #2563eb;
            }
            QPushButton:disabled {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e8ecf4, stop:1 #d4dae6);
                color: #64748b;
                border: 1px solid #b0bdd4;
            }

            QTableWidget, QListWidget, QTextEdit {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fafdff, stop:0.55 #eef4fc, stop:1 #e0eaf4);
                color: #0f172a;
                border: 1px solid #8fa3c4;
                border-radius: 12px;
                gridline-color: #b8cbe0;
                selection-background-color: #bfdbfe;
                selection-color: #0f172a;
            }
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #64748b, stop:1 #334155);
                color: #f1f5f9;
                border: none;
                border-right: 1px solid #475569;
                border-bottom: 2px solid #0f172a;
                padding: 9px 8px;
                font-weight: 700;
            }
            QTableWidget::item { padding: 7px 8px; }
            QListWidget::item { padding: 7px 12px; }
            QListWidget::item:selected { background-color: #bfdbfe; color: #0f172a; }

            /* ---------- Scrollbars ---------- */
            QScrollBar:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #94a3b8, stop:1 #cbd5e1);
                width: 12px;
                margin: 4px 2px 4px 2px;
                border-radius: 5px;
                border: 1px solid #64748b;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #64748b, stop:1 #334155);
                min-height: 28px;
                border-radius: 5px;
                border: 1px solid #475569;
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #475569, stop:1 #1e293b);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

            /* ---------- Sidebar ---------- */
            QFrame#sideRail {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #5b6b7e, stop:0.5 #4b5a6c, stop:1 #3a4555);
                border-right: 2px solid #1e293b;
            }
            QFrame#sideContent {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f0f5fc, stop:0.5 #e2eaf6, stop:1 #d8e4f2);
            }
            QToolButton#navBtn {
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 7px;
                background-color: transparent;
            }
            QToolButton#navBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #64748b, stop:1 #475569);
                border: 1px solid #94a3b8;
            }
            QToolButton#navBtn:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #38bdf8, stop:1 #1d4ed8);
                border: 2px solid #7dd3fc;
            }
            QTreeWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f5fbfa, stop:0.5 #eef6f9, stop:1 #e5edf5);
                border: 1px solid #8fa3c4;
            }
            QTreeWidget::item { padding: 7px 6px; }
            QTreeWidget::item:selected { background-color: #bfdbfe; color: #0c1929; }
            QCheckBox::indicator {
                width: 34px; height: 18px;
                border-radius: 9px;
                background: #d8e4f4;
                border: 1px solid #7f96bd;
            }
            QCheckBox::indicator:checked { background: #2563eb; border: 1px solid #1d4ed8; }
            QCheckBox::indicator::unchecked { image: none; }
            QCheckBox::indicator::checked { image: none; }
            QSlider::groove:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0f172a, stop:1 #334155);
                width: 6px;
                border-radius: 3px;
                border: 1px solid #020617;
            }
            QSlider::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #93c5fd, stop:1 #2563eb);
                height: 18px;
                margin: 0 -4px;
                border-radius: 6px;
                border: 1px solid #e2e8f0;
            }
            QSlider::sub-page:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #38bdf8, stop:1 #0284c7);
                border-radius: 3px;
            }
            QSlider::add-page:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e293b, stop:1 #334155);
                border-radius: 3px;
            }
            QFrame#rightTools {
                background-color: rgba(15, 23, 42, 0.88);
                border: 1px solid #020617;
                border-radius: 14px;
                margin: 10px;
                padding: 6px;
            }
            QToolButton#toolBtn {
                border: 1px solid #475569;
                border-radius: 11px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #475569, stop:1 #1e293b);
            }
            QToolButton#toolBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #64748b, stop:1 #334155);
                border: 1px solid #94a3b8;
            }
            QToolButton#toolBtn:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2563eb, stop:1 #1e3a8a);
                border: 1px solid #60a5fa;
            }

            QLabel#gcsMonoHint {
                color: #334155;
                font-size: 11px;
                line-height: 1.45;
            }
            QFrame#gcsBottomRadar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #e0f7fa, stop:0.45 #e8f4fc, stop:1 #d4e4f2);
                border: 2px solid #0891b2;
                border-radius: 8px;
            }
            QLabel#gcsRadarTitle {
                font-size: 13px;
                font-weight: 700;
                color: #0c4a6e;
                letter-spacing: 0.3px;
            }

            QFrame#gcsWeatherCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fff7ed, stop:0.4 #f0f7ff, stop:1 #e0ecfa);
                border: 2px solid #dc2626;
                border-radius: 8px;
                padding: 2px;
            }
            QFrame#gcsWeatherMiniBox {
                background-color: rgba(255, 255, 255, 0.7);
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QFrame#gcsWeatherLocationBox {
                background-color: rgba(255, 255, 255, 0.5);
                border: 1px solid #e2e8f0;
                border-radius: 5px;
            }
            QLabel#gcsWeatherTitle {
                font-size: 14px;
                font-weight: 700;
                color: #0c1929;
                letter-spacing: 0.3px;
            }
            QLabel#gcsWeatherCondition { font-size: 13px; font-weight: 600; color: #1e293b; }
            QLabel#gcsWeatherTemp { font-size: 24px; font-weight: 800; color: #b91c1c; }
            QLabel#gcsWeatherSub { font-size: 12px; font-weight: 600; color: #334155; }
            QLabel#gcsWeatherHint { font-size: 11px; font-weight: 600; color: #475569; }
            QLabel#gcsWeatherValue { font-size: 12px; font-weight: 600; color: #1d4ed8; }
            QLabel#gcsWeatherAqi { font-size: 12px; font-weight: 700; color: #15803d; }

            QFrame#gcsSensorCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e293b, stop:0.45 #0f172a, stop:1 #1a2332);
                border: 2px solid #3b82f6;
                border-radius: 8px;
            }
            QLabel#gcsSensorTitle {
                font-size: 13px;
                font-weight: 700;
                color: #e2e8f0;
                letter-spacing: 0.3px;
            }

            QFrame#uavStripCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f5f3ff, stop:0.5 #eef4fc, stop:1 #e0e7ff);
                border: 1px solid #818cf8;
                border-radius: 14px;
            }
            QLabel#uavStripTitle {
                font-weight: 700;
                color: #0c1929;
                font-size: 13px;
                letter-spacing: 0.2px;
            }
            QLabel#uavStripBody {
                color: #334155;
                font-size: 12px;
                line-height: 1.45;
            }
            """
        )

    @staticmethod
    def _pymavlink_available() -> bool:
        try:
            import pymavlink  # noqa: F401

            return True
        except Exception:
            return False

    @staticmethod
    def _enumerate_serial_ports() -> List[str]:
        try:
            from serial.tools import list_ports

            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    def _refresh_serial_ports_combo(self) -> None:
        self.serial_ports_combo.clear()
        ports = self._enumerate_serial_ports()
        for p in ports:
            self.serial_ports_combo.addItem(p)
        if not ports:
            self.serial_ports_combo.addItem("（未发现串口或未安装 pyserial）")
        self.statusBar().showMessage(f"已枚举 {len(ports)} 个串口", 4000)

    def _copy_serial_pick_to_mavlink_edit(self) -> None:
        t = self.serial_ports_combo.currentText().strip()
        if t and not t.startswith("（"):
            self.edit_mavlink_uri.setText(t)

    def _copy_serial_pick_to_adsb_edit(self) -> None:
        t = self.serial_ports_combo.currentText().strip()
        if t and not t.startswith("（"):
            self.edit_adsb_port.setText(t)

    def _stop_mavlink_worker_for(self, drone_id: str) -> None:
        w = self._mav_workers.pop(drone_id, None)
        if w is None:
            return
        try:
            w.disconnect_drone()
        except Exception:
            pass
        try:
            w.stop()
            w.wait(5000)
        except Exception:
            pass

    def _stop_all_mavlink_workers(self) -> None:
        for did in list(self._mav_workers.keys()):
            self._stop_mavlink_worker_for(did)

    def _ensure_mavlink_worker(self, cfg: Dict[str, Any]) -> DroneTelemetryWorker | None:
        did = str(cfg["id"])
        uri = str(cfg.get("port", "")).strip()
        baud = int(cfg.get("baud", 57600))
        if did in self._mav_workers:
            w = self._mav_workers[did]
            if getattr(w, "connection_uri", "") == uri and int(getattr(w, "baudrate", 0)) == baud:
                return w
            self._stop_mavlink_worker_for(did)
        if not self._pymavlink_available():
            return None
        if not uri:
            return None
        w = DroneTelemetryWorker(
            did,
            str(cfg.get("name", did)),
            uri,
            baud,
            parent=self,
        )
        w.telemetryUpdated.connect(self._on_real_telemetry)
        w.statusUpdated.connect(lambda m, d=did: self.statusBar().showMessage(f"[{d}] {m}", 8000))
        w.connectionChanged.connect(self._on_mavlink_connection_changed)
        w.start()
        self._mav_workers[did] = w
        return w

    def _apply_mavlink_settings_from_ui(self) -> None:
        uri = self.edit_mavlink_uri.text().strip()
        baud = int(self.spin_mavlink_baud.value())
        did = (self.edit_mavlink_drone_id.text() or "REAL-1").strip()
        dname = (self.edit_mavlink_drone_name.text() or "实机").strip()
        self._gcs["mavlink_connection"] = uri
        self._gcs["mavlink_baud"] = baud
        self._gcs["mavlink_drone_id"] = did
        self._gcs["mavlink_drone_name"] = dname
        merged = False
        for c in self._real_drone_configs:
            if str(c.get("id")) == did:
                c["name"] = dname
                c["port"] = uri
                c["baud"] = baud
                merged = True
                break
        if not merged and uri:
            self._real_drone_configs.append(
                {
                    "id": did,
                    "name": dname,
                    "emoji": "📡",
                    "model": "MAVLink",
                    "port": uri,
                    "baud": baud,
                    "pilot": {"name": "", "email": "", "phone": ""},
                }
            )
        self._stop_mavlink_worker_for(did)
        self._rebuild_drone_cards()
        self._init_mavlink_and_adsb_ui()
        self.statusBar().showMessage("MAVLink 参数已保存；请在对应无人机卡上点击「连接」。", 6000)

    def _apply_adsb_settings_from_ui(self) -> None:
        port = self.edit_adsb_port.text().strip()
        baud = int(self.spin_adsb_baud.value())
        self._gcs["adsb_serial_port"] = port
        self._gcs["adsb_serial_baud"] = baud
        if self._adsb_reader is not None:
            self._disconnect_adsb()
        self._init_mavlink_and_adsb_ui()
        self.statusBar().showMessage("ADS-B 串口参数已保存。", 4000)

    def _init_mavlink_and_adsb_ui(self) -> None:
        uri = (self._gcs.get("mavlink_connection") or "").strip()
        if uri:
            if self._pymavlink_available():
                self.lbl_mavlink.setText(f"已配置连接: {uri}\n点击「连接实机」开始 MAVLink 遥测线程拉取。")
                self.btn_mavlink.setEnabled(True)
            else:
                self.lbl_mavlink.setText(f"已配置 {uri}，但当前环境未安装 pymavlink。\n请执行: pip install pymavlink")
                self.btn_mavlink.setEnabled(False)
        else:
            self.lbl_mavlink.setText(
                "当前未填写 MAVLink 连接。可在上方输入 COM 口（如 COM15）或 udp: 地址，填写后点「应用 MAVLink 设置」。"
            )
            self.btn_mavlink.setEnabled(False)

        ad = (self._gcs.get("adsb_serial_port") or "").strip()
        if ad:
            self.lbl_adsb.setText(f"串口: {ad}  波特率 {int(self._gcs.get('adsb_serial_baud', 921600))}\n需 pyserial；解码需 rs1090。")
            self.btn_adsb.setEnabled(True)
        else:
            self.lbl_adsb.setText("未填写 ADS-B 串口。可在上方输入后点「应用 ADS-B 串口」，再点「连接 ADS-B」。")
            self.btn_adsb.setEnabled(False)

    def _init_hardware_workers(self) -> None:
        if bool(self._gcs.get("mavlink_autoconnect")) and (self._gcs.get("mavlink_connection") or "").strip():
            for cfg in self._real_drone_configs:
                w = self._ensure_mavlink_worker(cfg)
                if w is not None:
                    w.connect_drone()
                    self.btn_mavlink.setText("断开实机")
                    break

        if bool(self._gcs.get("adsb_autoconnect")) and (self._gcs.get("adsb_serial_port") or "").strip():
            self._connect_adsb()

    def _on_real_telemetry(self, payload: dict) -> None:
        did = str(payload.get("id", ""))
        if did:
            self._real_telemetry[did] = dict(payload)

    def _on_mavlink_connection_changed(self, drone_id: str, connected: bool) -> None:
        if drone_id in self._drone_cards:
            self._drone_cards[drone_id].set_connected(connected)
        any_on = any(w.is_connected for w in self._mav_workers.values())
        self._mavlink_connected = any_on
        self.btn_mavlink.setText("断开实机" if any_on else "连接实机")

    def _toggle_mavlink(self) -> None:
        """通信页快捷：全部断开 / 为首个实机配置发起连接。"""
        any_on = any(w.is_connected for w in self._mav_workers.values())
        if any_on:
            for w in self._mav_workers.values():
                w.disconnect_drone()
            return
        for cfg in self._real_drone_configs:
            w = self._ensure_mavlink_worker(cfg)
            if w is not None:
                w.connect_drone()
                return

    def _connect_adsb(self) -> bool:
        port = (self._gcs.get("adsb_serial_port") or "").strip()
        if not port:
            return False
        if self._adsb_reader is not None:
            return True
        baud = int(self._gcs.get("adsb_serial_baud", 921600))
        clear_adsb_cache()
        reader = ADSBSerialReader(port, baud, decode_and_update)
        if not reader.connect():
            self.lbl_adsb.setText(self.lbl_adsb.text() + "\n串口打开失败。")
            return False
        reader.start_reading()
        self._adsb_reader = reader
        self._adsb_connected = True
        self.btn_adsb.setText("断开 ADS-B")
        return True

    def _disconnect_adsb(self) -> None:
        if self._adsb_reader:
            self._adsb_reader.disconnect()
            self._adsb_reader = None
        clear_adsb_cache()
        self._adsb_connected = False
        self.btn_adsb.setText("连接 ADS-B")

    def _toggle_adsb(self) -> None:
        if self._adsb_reader is not None:
            self._disconnect_adsb()
        else:
            self._connect_adsb()

    def _toggle_fullscreen(self, checked: bool) -> None:
        """切换全屏模式"""
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _refresh_peripherals_ui(self) -> None:
        self._sync_drone_cards_telemetry()
        self._refresh_stand_cards_state()
        if not self.timer.isActive():
            self._refresh_gcs_panels_from_snapshot()
        self._refresh_demo_live_narrative()

    def _refresh_demo_live_narrative(self) -> None:
        text = self._build_demo_live_narrative_text()
        if text == self._demo_live_narrative_cache:
            return
        sb = self._demo_live_feed.verticalScrollBar()
        if sb.isSliderDown():
            return
        self._demo_live_narrative_cache = text
        old_val = sb.value()
        old_max = max(1, sb.maximum())
        at_top = old_val <= 2
        at_bottom = sb.maximum() > 0 and old_val >= sb.maximum() - 4
        self._demo_live_feed.setPlainText(text)

        def _restore_scroll() -> None:
            sbr = self._demo_live_feed.verticalScrollBar()
            nm = sbr.maximum()
            if at_top or nm <= 0:
                sbr.setValue(0)
            elif at_bottom:
                sbr.setValue(nm)
            else:
                ratio = old_val / old_max
                sbr.setValue(int(min(nm, ratio * nm)))

        QTimer.singleShot(0, _restore_scroll)

    def _build_demo_live_narrative_text(self) -> str:
        eng = self.engine
        lines: List[str] = []
        lines.append("══ 演示实况（随仿真刷新）══")
        tag = self._demo_live_scene_tag.strip()
        lines.append(f"当前片段：{tag or '（待机：点「演示」或任务页添加后会有场景标签）'}")
        sim_on = "运行中" if self.timer.isActive() else "已暂停"
        lines.append(f"仿真时钟 t = {eng.now:.1f} s　主仿真：{sim_on}")

        drones = eng.drones
        if not drones:
            lines.append("")
            lines.append("当前无仿真任务机。开始演示或从任务页加入后，此处会显示无人机进入等待区及机位分配情况。")
            return "\n".join(lines)

        lines.append("")
        lines.append("【无人机进入与分配情况】")

        for d in sorted(drones, key=lambda x: x.drone_id):
            spec = d.spec
            if not spec:
                continue

            sz = f"{spec.size:.2f}m"
            bat = f"{d.battery_percent:.0f}%"
            pri = d.priority
            sid = d.assigned_slot_id or "未分配"

            lines.append(
                f"  · {d.drone_id}：尺寸 {sz}，电量 {bat}，优先级 {pri} → 分配至机位 {sid}"
            )

            # 显示详细的分配原因
            if d.assignment_rationale:
                rationale_lines = d.assignment_rationale.split('\n')
                for line in rationale_lines:
                    lines.append(f"    {line}")
                lines.append("")

        lines.append("【机位占用状态】")
        for s in eng.slots:
            occ = s.occupied_by or "空闲"
            lines.append(f"  · {s.slot_id}（{s.display_name}）→ {occ}")

        return "\n".join(lines)

    def _seed_real_configs_from_gcs(self) -> None:
        if self._real_drone_configs:
            return
        uri = (self._gcs.get("mavlink_connection") or "").strip()
        if not uri:
            return
        self._real_drone_configs.append(
            {
                "id": str(self._gcs.get("mavlink_drone_id", "REAL-1")),
                "name": str(self._gcs.get("mavlink_drone_name", "实机")),
                "emoji": "📡",
                "model": "MAVLink",
                "port": uri,
                "baud": int(self._gcs.get("mavlink_baud", 57600)),
                "pilot": {"name": "", "email": "", "phone": ""},
            }
        )

    @staticmethod
    def _stand_info_dict(slot) -> dict:
        return StandAssignDialog.stand_info_dict(slot)

    def _rebuild_stand_cards(self) -> None:
        while self._stand_cards_layout.count():
            it = self._stand_cards_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._stand_cards.clear()
        for slot in self.engine.slots:
            card = GcsStandInfoCard(slot.slot_id, slot.display_name, slot.stand_type or "outdoor")
            card.apply_slot_constraints(slot)
            self._stand_cards[slot.slot_id] = card
            card.release_stand_clicked.connect(self._on_stand_release)
            card.delete_stand_clicked.connect(self._on_stand_delete)
            card.edit_stand_clicked.connect(self._on_stand_edit)
            self._stand_cards_layout.addWidget(card)
        self._stand_cards_layout.addStretch(1)
        self._refresh_stand_cards_state()

    def _refresh_stand_cards_state(self) -> None:
        for slot in self.engine.slots:
            c = self._stand_cards.get(slot.slot_id)
            if not c:
                continue
            c.set_occupied(slot.occupied_by)

    def _on_stand_release(self, stand_id: str) -> None:
        ok, msg = self.engine.force_release_slot(stand_id)
        self.statusBar().showMessage(msg, 5000)
        if ok:
            self._refresh_stand_cards_state()
            self._sync_drone_cards_telemetry()
            self.map_canvas.update()

    def _on_stand_delete(self, stand_id: str) -> None:
        ok, msg = self.engine.remove_slot(stand_id)
        if not ok:
            QMessageBox.warning(self, "删除机位", msg)
            return
        self._rebuild_stand_cards()
        self.map_canvas.update()

    def _on_stand_edit(self, stand_id: str) -> None:
        slot = next((s for s in self.engine.slots if s.slot_id == stand_id), None)
        if slot is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑机位 {stand_id}")
        form = QFormLayout()
        name_e = QLineEdit(slot.name or slot.slot_id)
        combo = QComboBox()
        combo.addItems(["outdoor", "indoor"])
        combo.setCurrentIndex(1 if (slot.stand_type or "outdoor") == "indoor" else 0)
        desc_e = QLineEdit(slot.description or "")
        fr = QDoubleSpinBox()
        fr.setRange(4.0, 80.0)
        fr.setValue(float(slot.footprint_radius_m))
        fr.setSuffix(" m")
        mx = QDoubleSpinBox()
        mx.setRange(0.5, 30.0)
        mx.setValue(float(slot.max_drone_size_m))
        mx.setSuffix(" m")
        sk = QDoubleSpinBox()
        sk.setRange(0.5, 500.0)
        sk.setValue(float(slot.station_charge_kw))
        sk.setSuffix(" kW")
        ck = QDoubleSpinBox()
        ck.setRange(0.5, 500.0)
        ck.setValue(float(slot.station_charge_cap_kw))
        ck.setSuffix(" kW")
        form.addRow("名称", name_e)
        form.addRow("类型", combo)
        form.addRow("描述", desc_e)
        form.addRow("保护区半径", fr)
        form.addRow("最大机型尺寸", mx)
        form.addRow("充电功率", sk)
        form.addRow("充电功率上限", ck)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        v = QVBoxLayout(dlg)
        v.addLayout(form)
        v.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cand = Slot(
            slot_id=slot.slot_id,
            center=slot.center,
            name=name_e.text().strip(),
            stand_type=combo.currentText(),
            description=desc_e.text().strip(),
            occupied_by=slot.occupied_by,
            occupied_until=slot.occupied_until,
            footprint_radius_m=float(fr.value()),
            max_drone_size_m=float(mx.value()),
            station_charge_kw=float(sk.value()),
            station_charge_cap_kw=float(ck.value()),
        )
        bad = candidate_conflicts_with_list(cand, self.engine.slots)
        if bad:
            QMessageBox.warning(self, "编辑机位", f"保护区与机位 {bad} 重叠，请缩小半径或调整。")
            return
        slot.name = cand.name
        slot.stand_type = cand.stand_type
        slot.description = cand.description
        slot.footprint_radius_m = cand.footprint_radius_m
        slot.max_drone_size_m = cand.max_drone_size_m
        slot.station_charge_kw = cand.station_charge_kw
        slot.station_charge_cap_kw = cand.station_charge_cap_kw
        c = self._stand_cards.get(stand_id)
        if c:
            c.set_name(slot.display_name)
            c.set_stand_type(slot.stand_type)
            c.apply_slot_constraints(slot)
        self.map_canvas.update()

    def _on_toggle_slot_placement_mode(self, on: bool) -> None:
        self._slot_placement_active = bool(on)
        self.map_canvas.set_slot_placement_mode(on)
        self.statusBar().showMessage(
            "请在地图绿色停机坪内点击以添加机位中心。" if on else "已取消地图选点。",
            5000,
        )

    def _on_map_slot_place_chosen(self, wx: float, wy: float) -> None:
        if not self._slot_placement_active:
            return
        self.btn_slot_pick_map.setChecked(False)
        self._on_toggle_slot_placement_mode(False)
        dlg = QDialog(self)
        dlg.setWindowTitle("新建机位")
        form = QFormLayout()
        eid = QLineEdit()
        eid.setPlaceholderText("例如 S5")
        ename = QLineEdit()
        ename.setPlaceholderText("显示名称")
        combo = QComboBox()
        combo.addItems(["outdoor", "indoor"])
        edesc = QLineEdit()
        fr = QDoubleSpinBox()
        fr.setRange(4.0, 80.0)
        fr.setValue(14.0)
        fr.setSuffix(" m")
        mx = QDoubleSpinBox()
        mx.setRange(0.5, 30.0)
        mx.setValue(5.0)
        mx.setSuffix(" m")
        sk = QDoubleSpinBox()
        sk.setRange(0.5, 500.0)
        sk.setValue(10.0)
        sk.setSuffix(" kW")
        ck = QDoubleSpinBox()
        ck.setRange(0.5, 500.0)
        ck.setValue(10.0)
        ck.setSuffix(" kW")
        form.addRow("机位 ID", eid)
        form.addRow("名称", ename)
        form.addRow("类型", combo)
        form.addRow("描述", edesc)
        form.addRow("保护区半径", fr)
        form.addRow("最大机型尺寸 ≤", mx)
        form.addRow("充电功率", sk)
        form.addRow("充电功率上限", ck)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        v = QVBoxLayout(dlg)
        v.addLayout(form)
        v.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sid = eid.text().strip()
        if not sid:
            QMessageBox.warning(self, "新建机位", "请填写机位 ID。")
            return
        slot = Slot(
            slot_id=sid,
            center=Vec2(float(wx), float(wy)),
            name=ename.text().strip(),
            stand_type=combo.currentText(),
            description=edesc.text().strip(),
            footprint_radius_m=float(fr.value()),
            max_drone_size_m=float(mx.value()),
            station_charge_kw=float(sk.value()),
            station_charge_cap_kw=float(ck.value()),
        )
        ok, msg = self.engine.add_slot(slot)
        if not ok:
            QMessageBox.warning(self, "新建机位", msg)
            return
        self._rebuild_stand_cards()
        self.map_canvas.update()
        self.statusBar().showMessage(msg, 5000)

    def _rebuild_drone_cards(self) -> None:
        while self._uav_cards_layout.count():
            it = self._uav_cards_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._drone_cards.clear()
        for d in self.engine.drones:
            model = d.spec.model if d.spec else "Sim"
            cfg: Dict[str, Any] = {
                "id": d.drone_id,
                "name": d.drone_id,
                "emoji": "🛩",
                "model": model,
                "port": "仿真",
                "baud": 0,
            }
            if d.spec:
                cfg["size_m"] = float(d.spec.size)
                cfg["charge_kw"] = float(d.spec.required_power)
                cfg["battery_kwh"] = resolved_battery_kwh(d.spec)
            card = GcsDroneInfoCard(cfg, sim_mode=True)
            self._wire_drone_card(card, sim=True)
            self._uav_cards_layout.addWidget(card)
            if d.drone_id not in self._drone_pilots:
                self._drone_pilots[d.drone_id] = self._default_sim_pilot(d.drone_id)
        for cfg in self._real_drone_configs:
            did = str(cfg["id"])
            p = cfg.get("pilot") or {}
            self._drone_pilots[did] = {
                "name": str(p.get("name", "")),
                "email": str(p.get("email", "")),
                "phone": str(p.get("phone", "")),
            }
            card = GcsDroneInfoCard(dict(cfg), sim_mode=False)
            self._wire_drone_card(card, sim=False)
            self._uav_cards_layout.addWidget(card)
        self._uav_cards_layout.addStretch(1)
        self._sync_drone_cards_telemetry()

    def _wire_drone_card(self, card: GcsDroneInfoCard, *, sim: bool) -> None:
        did = card.drone_id
        self._drone_cards[did] = card
        card.remove_clicked.connect(lambda _id=did, s=sim: self._on_remove_drone_card(_id, sim=s))
        card.assign_stand_clicked.connect(lambda _id=did: self._on_drone_assign_slot_dialog(_id))
        card.release_stand_clicked.connect(lambda _id=did: self._on_drone_release_stand(_id))
        card.connect_clicked.connect(lambda _id, on, d=did: self._on_card_mavlink_connect(d, on))
        card.pilot_info_clicked.connect(lambda _id=did: self._on_pilot_info(_id))
        card.mavlink_settings_clicked.connect(lambda _id=did: self._on_drone_mavlink_settings(_id))

    def _on_remove_drone_card(self, drone_id: str, *, sim: bool) -> None:
        if sim:
            ok, msg = self.engine.remove_drone(drone_id)
            if not ok:
                QMessageBox.warning(self, "移除无人机", msg)
                return
            self._drone_pilots.pop(drone_id, None)
        else:
            self._real_drone_configs[:] = [c for c in self._real_drone_configs if str(c.get("id")) != drone_id]
            self._stop_mavlink_worker_for(drone_id)
            self._drone_pilots.pop(drone_id, None)
        self._rebuild_drone_cards()
        self._rebuild_stand_cards()

    def _on_drone_assign_slot_dialog(self, drone_id: str) -> None:
        drone = next((d for d in self.engine.drones if d.drone_id == drone_id), None)
        if drone is None:
            QMessageBox.information(self, "机位分配", "实机卡片请在任务页加入仿真机队后再分配，或使用仿真无人机。")
            return
        dlg = StandAssignDialog(
            drone_id,
            drone_id,
            drone.spec.model if drone.spec else "",
            self.engine.slots,
            self.engine.now,
            compat_drone=drone,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sid = dlg.selected_slot_id()
        if not sid:
            return
        ok, msg = self.engine.manual_assign_slot(drone_id, sid)
        self.statusBar().showMessage(msg, 6000)
        if ok:
            slot = next((s for s in self.engine.slots if s.slot_id == sid), None)
            if slot and drone_id in self._drone_cards:
                info = self._stand_info_dict(slot)
                self._drone_cards[drone_id].set_assigned_stand(sid, info)
                self._maybe_email_pilot_stand_assigned(drone_id, info)
            self._refresh_stand_cards_state()
            self.map_canvas.update()

    def _on_drone_release_stand(self, drone_id: str) -> None:
        ok, msg = self.engine.release_stand_assignment(drone_id)
        self.statusBar().showMessage(msg, 5000)
        if ok and drone_id in self._drone_cards:
            self._drone_cards[drone_id].set_assigned_stand(None, None)
            self._refresh_stand_cards_state()
            self.map_canvas.update()

    def _on_card_mavlink_connect(self, drone_id: str, want_connect: bool) -> None:
        cfg = next((c for c in self._real_drone_configs if str(c.get("id")) == drone_id), None)
        if not cfg:
            return
        w = self._ensure_mavlink_worker(cfg)
        if w is None:
            QMessageBox.warning(
                self,
                "MAVLink",
                "无法创建连接：请检查串口/地址是否填写，并安装 pymavlink。",
            )
            return
        if want_connect:
            w.connect_drone()
        else:
            w.disconnect_drone()

    def _on_pilot_info(self, drone_id: str) -> None:
        cur = self._drone_pilots.get(
            str(drone_id),
            {"name": "", "email": "", "phone": ""},
        )
        dlg = PilotInfoDialog(cur.get("name", ""), cur.get("email", ""), cur.get("phone", ""), parent=self)
        dlg.current_drone_id = str(drone_id)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.get_values()
        self._drone_pilots[str(drone_id)] = vals
        for c in self._real_drone_configs:
            if str(c.get("id")) == str(drone_id):
                c["pilot"] = vals
                break
        self.statusBar().showMessage(f"👨‍✈️ 已保存无人机 {drone_id} 的飞手信息", 5000)

    def _on_drone_mavlink_settings(self, drone_id: str) -> None:
        cfg = next((c for c in self._real_drone_configs if str(c.get("id")) == drone_id), None)
        if not cfg:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"MAVLink 连接 — {drone_id}")
        form = QFormLayout()
        port_e = QLineEdit(str(cfg.get("port", "")))
        baud_s = QSpinBox()
        baud_s.setRange(1200, 921600)
        baud_s.setValue(int(cfg.get("baud", 57600)))
        form.addRow("连接（COM / udp:）:", port_e)
        form.addRow("波特率:", baud_s)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(bb)
        v = QVBoxLayout(dlg)
        v.addLayout(form)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        uri = port_e.text().strip()
        if not uri:
            QMessageBox.warning(self, "MAVLink", "连接不能为空。")
            return
        baud = int(baud_s.value())
        cfg["port"] = uri
        cfg["baud"] = baud
        if drone_id in self._drone_cards:
            self._drone_cards[drone_id].set_port_baud(uri, baud)
        self._stop_mavlink_worker_for(drone_id)
        self.statusBar().showMessage(f"已更新 {drone_id} 的 MAVLink 参数，请在卡片上重新连接。", 6000)

    def _on_add_real_drone(self) -> None:
        sug = "REAL-1"
        n = 1
        while any(str(c.get("id")) == sug for c in self._real_drone_configs) or any(d.drone_id == sug for d in self.engine.drones):
            n += 1
            sug = f"REAL-{n}"
        dlg = AddRealDroneDialog(suggested_id=sug, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pack = dlg.get_config()
        did = pack["id"]
        if any(str(c.get("id")) == did for c in self._real_drone_configs) or any(d.drone_id == did for d in self.engine.drones):
            QMessageBox.warning(self, "添加实机", "ID 与已有仿真机或实机重复。")
            return
        if not pack.get("port"):
            QMessageBox.warning(self, "添加实机", "请填写 MAVLink 连接。")
            return
        pilot = pack.pop("pilot", {})
        auto = pack.pop("auto_connect", False)
        self._real_drone_configs.append({**pack, "pilot": pilot})
        self._drone_pilots[did] = {
            "name": pilot.get("name", ""),
            "email": pilot.get("email", ""),
            "phone": pilot.get("phone", ""),
        }
        self._rebuild_drone_cards()
        if auto and self._pymavlink_available():
            w = self._ensure_mavlink_worker(next(c for c in self._real_drone_configs if str(c["id"]) == did))
            if w is not None:
                w.connect_drone()

    def _sync_drone_cards_telemetry(self) -> None:
        for d in self.engine.drones:
            card = self._drone_cards.get(d.drone_id)
            if not card:
                continue
            w_lat, w_lon = world_meters_to_wgs84(self._gs_lat, self._gs_lon, d.position.x, d.position.y)
            slot_d = (
                next((s for s in self.engine.slots if s.slot_id == d.assigned_slot_id), None)
                if d.assigned_slot_id
                else None
            )
            card.update_data(
                w_lat,
                w_lon,
                float(d.altitude),
                float(d.battery_percent),
                None,
                charge_w=d.charging_power_watts(slot_d),
            )
            if d.assigned_slot_id:
                slot = next((s for s in self.engine.slots if s.slot_id == d.assigned_slot_id), None)
                if slot:
                    card.set_assigned_stand(d.assigned_slot_id, self._stand_info_dict(slot))
            else:
                card.set_assigned_stand(None, None)
        for cfg in self._real_drone_configs:
            did = str(cfg["id"])
            card = self._drone_cards.get(did)
            if not card:
                continue
            t = self._real_telemetry.get(did, {})
            w = self._mav_workers.get(did)
            conn = bool(t.get("connected", w.is_connected if w else False))
            card.set_connected(conn)
            card.update_data(
                t.get("lat"),
                t.get("lng"),
                t.get("alt"),
                t.get("battery"),
                t.get("sats"),
                charge_w=t.get("charge_w"),
            )

    def _bootstrap_location_and_weather(self) -> None:
        gps_port = (self._gcs.get("gps_serial_port") or "").strip() or None
        gps_baud = int(self._gcs.get("gps_serial_baud", 115200))
        lat, lon = get_location_sync(gps_port, gps_baud)
        if lat is not None and lon is not None:
            if gps_port:
                src = "硬件 GNSS (NMEA 串口)"
            else:
                src = "Windows 系统定位"
            self._apply_ground_station(float(lat), float(lon), source=src)
        else:
            self._apply_ground_station(self._gs_lat, self._gs_lon, source="配置默认（GNSS 与系统定位均不可用）")
        if self._weather_api_key:
            self._start_weather_fetch(force_refresh=True)
            self._weather_timer.start()

    def _apply_ground_station(self, lat: float, lon: float, *, source: str = "") -> None:
        self._gs_lat, self._gs_lon = lat, lon
        self.map_canvas.set_geo_reference(self._gs_lat, self._gs_lon)
        self.bottom_radar.set_center(self._gs_lat, self._gs_lon)
        self.bottom_weather.update_station_info(self._gs_lat, self._gs_lon)
        src = f"\n来源: {source}" if source else ""
        self.comm_station_label.setText(f"纬度 {self._gs_lat:.6f}\n经度 {self._gs_lon:.6f}{src}")
        self._refresh_gcs_panels_from_snapshot()

    def _on_refresh_ground_station_location(self) -> None:
        gps_port = (self._gcs.get("gps_serial_port") or "").strip() or None
        gps_baud = int(self._gcs.get("gps_serial_baud", 115200))
        lat, lon = get_location_sync(gps_port, gps_baud)
        if lat is None or lon is None:
            self.comm_station_label.setText(
                f"纬度 {self._gs_lat:.6f}\n经度 {self._gs_lon:.6f}\n来源: 刷新失败，保持当前坐标"
            )
            return
        src = "硬件 GNSS (NMEA)" if gps_port else "Windows 系统定位"
        self._apply_ground_station(float(lat), float(lon), source=src)
        if self._weather_api_key:
            self._start_weather_fetch(force_refresh=True)

    def _weather_thread_is_running(self) -> bool:
        """QThread 在 deleteLater 后 C++ 侧可能已销毁，需避免对已删除对象调用 isRunning()。"""
        wt = self._weather_thread
        if wt is None:
            return False
        try:
            return wt.isRunning()
        except RuntimeError:
            self._weather_thread = None
            return False

    def _discard_finished_weather_thread(self) -> None:
        self._weather_thread = None

    def _start_weather_fetch(self, *, force_refresh: bool) -> None:
        if not self._weather_api_key:
            err = {
                "error": "未配置天气 API Key（gcs.weather_api_key 或 WEATHERAPI_KEY）",
                "last_updated": None,
            }
            self.bottom_weather.update_weather(err)
            return
        if self._weather_thread_is_running():
            return
        th = _WeatherFetchThread(
            self._weather_api_key, self._gs_lat, self._gs_lon, self._weather_cache, force_refresh=force_refresh
        )
        self._weather_thread = th
        th.succeeded.connect(self._on_weather_succeeded)
        th.failed.connect(self._on_weather_failed)
        # 先清空主窗口引用，再 deleteLater，避免下次点击对已销毁的 QThread 调用 isRunning()
        th.finished.connect(self._discard_finished_weather_thread)
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_weather_succeeded(self, data: dict) -> None:
        if self._location_name_override:
            data["location_name"] = self._location_name_override
        self.bottom_weather.update_weather(data)
        updated = data.get("last_updated")
        self.bottom_weather.update_station_info(self._gs_lat, self._gs_lon, updated_at=str(updated) if updated else None)

    def _on_weather_failed(self, message: str) -> None:
        self.bottom_weather.update_weather({"error": message, "last_updated": None})

    def _refresh_bottom_radar_title(self) -> None:
        r_km = self.bottom_radar.calculate_display_range() / 1000.0
        n = len(self.bottom_radar.targets)
        self.bottom_radar_title.setText(f"ADS-B {r_km:.1f} km  ·  目标 {n}")

    def _build_radar_targets(self, drones: list, sim_time: float) -> list[dict]:
        targets: list[dict] = []
        for _tid, telem in sorted(self._real_telemetry.items()):
            la, lo = telem.get("lat"), telem.get("lng")
            if la is None or lo is None:
                continue
            name = str(telem.get("name") or _tid)
            targets.append({"lat": float(la), "lon": float(lo), "name": f"REAL:{name[:10]}", "kind": "REAL"})

        for icao, row in self._last_adsb_snapshot.items():
            la, lo = row.get("lat"), row.get("lon")
            if la is None or lo is None:
                continue
            label = (row.get("callsign") or icao or "?").strip() or icao
            targets.append({"lat": float(la), "lon": float(lo), "name": f"ADSB:{label[:10]}", "kind": "ADSB"})

        for d in drones:
            lat, lon = world_meters_to_wgs84(self._gs_lat, self._gs_lon, d.position.x, d.position.y)
            targets.append({"lat": lat, "lon": lon, "name": d.drone_id, "kind": "SIM"})

        if bool(self._gcs.get("radar_show_demo_aux", True)):
            for i in range(3):
                ang = math.radians(120 * i + (sim_time * 18.0) % 360.0)
                dist = 2800.0 + i * 500.0
                dx = dist * math.sin(ang)
                dy = dist * math.cos(ang)
                la, lo = world_meters_to_wgs84(self._gs_lat, self._gs_lon, dx, dy)
                targets.append({"lat": la, "lon": lo, "name": f"DEMO-{i + 1}", "kind": "DEMO"})
        return targets

    def closeEvent(self, event) -> None:  # noqa: N802
        self._demo_sequence_timer.stop()
        self._weather_timer.stop()
        self._radar_title_timer.stop()
        try:
            self._peripheral_timer.stop()
        except Exception:
            pass
        self._stop_all_mavlink_workers()
        self._disconnect_adsb()
        wt = self._weather_thread
        if wt is not None:
            try:
                if wt.isRunning():
                    wt.wait(4000)
            except RuntimeError:
                pass
            self._weather_thread = None
        super().closeEvent(event)

    def _on_start_clicked(self) -> None:
        self._ensure_sim_timer_running()
        self._start_sequential_demo_playback()

    def _ensure_sim_timer_running(self) -> None:
        if not self.timer.isActive():
            self.timer.start()

    def _cancel_sequential_demo(self) -> None:
        self._sequential_demo_active = False
        self._demo_sequence_timer.stop()

    def _clear_simulation_for_new_demo(self) -> None:
        self.engine.reset_demo_state()
        self._demo_live_scene_tag = ""
        self._pilot_deviation_alert_seen.clear()
        self._rebuild_drone_cards()
        self._rebuild_stand_cards()
        self.map_canvas.update_state(self.engine.drones)
        self.assign_result.setText("分配结果: -")
        self.status_table.setRowCount(0)
        self.alert_list.clear()
        self.time_label.setText("System Time: t=0.0s")
        self._refresh_gcs_panels_from_snapshot()
        self._demo_live_narrative_cache = ""
        self._refresh_demo_live_narrative()

    def _start_sequential_demo_playback(self) -> None:
        self._cancel_sequential_demo()
        self._sequential_demo_active = True
        self._demo_scenario_index = 0
        self._clear_simulation_for_new_demo()
        self._run_current_demo_scenario()
        self._demo_sequence_timer.start()

    def _run_current_demo_scenario(self) -> None:
        name, rows = self._demo_scenarios[self._demo_scenario_index]
        total = len(self._demo_scenarios)
        self._demo_live_scene_tag = f"自动连播 ({self._demo_scenario_index + 1}/{total})「{name}」"
        n_added, last_msg, first_id = self._spawn_demo_mission_rows(rows)
        self.assign_result.setText(f"自动演示 ({self._demo_scenario_index + 1}/{total}) {name}: {last_msg}")
        if first_id:
            self._seed_demo_pilot_for_notify_email(first_id)
        self._rebuild_drone_cards()
        self._rebuild_stand_cards()
        self.map_canvas.update()
        self._refresh_demo_live_narrative()
        if n_added == 0:
            self.statusBar().showMessage(f"自动演示失败：未能生成「{name}」批次无人机", 8000)
            self._cancel_sequential_demo()
        elif first_id:
            self._notify_pilot_if_drone_has_assigned_slot(first_id)

    def _tick_demo_sequence(self) -> None:
        if not self._sequential_demo_active:
            return
        if not self.engine.drones:
            self._cancel_sequential_demo()
            self.statusBar().showMessage("自动演示已中止：场景中无仿真无人机", 8000)
            return
        if all(d.status == DroneStatus.FINISHED for d in self.engine.drones):
            self._advance_to_next_demo_scenario()

    def _advance_to_next_demo_scenario(self) -> None:
        self._demo_scenario_index += 1
        if self._demo_scenario_index >= len(self._demo_scenarios):
            self._sequential_demo_active = False
            self._demo_sequence_timer.stop()
            self.statusBar().showMessage("全部场景演示已结束（三档均已播放完毕）", 10000)
            self.assign_result.setText("演示：全部场景已结束")
            self._clear_simulation_for_new_demo()
            return
        self._clear_simulation_for_new_demo()
        self._run_current_demo_scenario()

    def _spawn_demo_mission_rows(self, rows: List[Tuple[str, str, float, float, float, int, float]]) -> Tuple[int, str, Optional[str]]:
        last_msg = ""
        ok_count = 0
        first_added_id: Optional[str] = None
        for uid, model, sz, pw, bat, priority, initial_soc in rows:
            if any(d.drone_id == uid for d in self.engine.drones):
                uid = f"{uid}-{len(self.engine.drones)}"
            ok, msg = self.engine.add_mission_drone(
                drone_id=uid,
                model=model,
                size=float(sz),
                required_power=float(pw),
                battery_capacity_kwh=float(max(0.0, bat)),
                priority=int(priority),
                battery_percent=float(initial_soc),
            )
            last_msg = msg
            if ok:
                ok_count += 1
                # 电量已经在 add_mission_drone 中设置，不需要再设置
                if first_added_id is None:
                    first_added_id = uid
            else:
                QMessageBox.warning(self, "演示批次", f"{uid}: {msg}")
                break
        return ok_count, last_msg, first_added_id

    def _run_demo_rows(self, rows: List[Tuple[str, str, float, float, float, int, float]]) -> None:
        _, last_msg, first_id = self._spawn_demo_mission_rows(rows)
        self.assign_result.setText(f"演示批次: {last_msg}")
        if first_id:
            self._seed_demo_pilot_for_notify_email(first_id)
        self._rebuild_drone_cards()
        self._rebuild_stand_cards()
        self.map_canvas.update()
        self._refresh_demo_live_narrative()
        if first_id:
            self._notify_pilot_if_drone_has_assigned_slot(first_id)

    def _on_demo_size_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景1：相同优先级-按停靠时长」·3架无人机优先级相同，按电量差异（停靠时长）排序"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[0][1])

    def _on_demo_power_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景2：不同优先级-高优先级优先」·3架无人机参数相同，优先级分别为0、5、10"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[1][1])

    def _on_demo_mixed_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景3：Best-Fit尺寸匹配」·3架不同尺寸无人机，分配到最接近的机位"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[2][1])

    def _on_demo_power_filter_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景4：功率筛选」·3架无人机功率需求不同，测试功率匹配筛选"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[3][1])

    def _on_demo_comprehensive_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景5：综合测试」·4架无人机，尺寸、功率、优先级、电量均不同"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[4][1])

    def _on_demo_battery_batch(self) -> None:
        self._cancel_sequential_demo()
        self._clear_simulation_for_new_demo()
        self._demo_live_scene_tag = "手动演示「场景6：电量差异」·3架相同参数无人机，电量分别为95%、50%、20%"
        self._ensure_sim_timer_running()
        self._run_demo_rows(self._demo_scenarios[5][1])

    def _inject_deviation(self) -> None:
        target = None
        for drone in self.engine.drones:
            if drone.status.value in ("inbound", "outbound") and drone.planned_route:
                target = drone
                break
        if target is None:
            self.statusBar().showMessage("无进场/离场中的无人机（需已生成规划路径）", 6000)
            return
        if target.demo_route_mode == "follow":
            target.demo_route_mode = "deviate"
            self._seed_demo_pilot_for_notify_email(target.drone_id)
            self.statusBar().showMessage(
                f"偏航演示：{target.drone_id} 已脱离规划路径侧移；持续超出阈值后将告警并发飞手邮件",
                9000,
            )
        elif target.demo_route_mode == "deviate":
            target.demo_route_mode = "recover"
            self.statusBar().showMessage(
                f"偏航演示：{target.drone_id} 正飞回规划路径，贴合后自动沿路径飞行",
                9000,
            )
        else:
            if self.engine.force_demo_route_follow(target.drone_id):
                self.statusBar().showMessage(f"偏航演示：{target.drone_id} 已立即贴合规划路径并恢复沿路径飞行", 8000)
            else:
                self.statusBar().showMessage("未能贴合路径（无规划路径或状态已变）", 6000)

    def _assign_drone(self) -> None:
        try:
            bat_raw = self.battery_kwh_input.text().strip()
            bat_kwh = float(bat_raw) if bat_raw else 0.0
            # 新增：读取电池电量百分比输入，默认 50%
            bat_percent_raw = self.battery_percent_input.text().strip()
            bat_percent = float(bat_percent_raw) if bat_percent_raw else 50.0
            # 限制电量范围在 0-100%
            bat_percent = max(0.0, min(100.0, bat_percent))
            added_id = self.id_input.text().strip()
            ok, msg = self.engine.add_mission_drone(
                drone_id=added_id,
                model=self.model_input.text().strip(),
                size=float(self.size_input.text().strip()),
                required_power=float(self.power_input.text().strip()),
                battery_capacity_kwh=float(max(0.0, bat_kwh)),
                priority=int(self.priority_input.value()),
                # 新增：传递电池电量百分比到引擎
                battery_percent=bat_percent,
            )
        except ValueError:
            added_id = ""
            ok, msg = False, "分配失败：输入参数格式错误"
        self.assign_result.setText(f"分配结果: {msg}")
        if ok:
            self._demo_live_scene_tag = "任务页手动添加"
            self.id_input.setText(f"UAV-{len(self.engine.drones)+100}")
            self._rebuild_drone_cards()
            self._rebuild_stand_cards()
            self.map_canvas.update()
            self._refresh_demo_live_narrative()
            if added_id:
                self._notify_pilot_if_drone_has_assigned_slot(added_id)

    def _refresh_gcs_panels_from_snapshot(self) -> None:
        self._last_adsb_snapshot = get_aircraft_snapshot(45.0)
        snap = self.engine.snapshot()
        drones = snap["drones"]
        targets = self._build_radar_targets(drones, float(snap["time"]))
        self.bottom_radar.set_targets(targets)
        lines = [f"{'名称':<14} {'纬度':<12} {'经度':<12} {'类型':<8}"]
        for t in targets:
            lines.append(
                f"{str(t.get('name', '')):<14} "
                f"{float(t['lat']):<12.6f} "
                f"{float(t['lon']):<12.6f} "
                f"{str(t.get('kind', '?')):<8}"
            )
        self.comm_radar_log.setPlainText("\n".join(lines))

        self.comm_drone_table.setRowCount(len(drones))
        for row, drone in enumerate(drones):
            w_lat, w_lon = world_meters_to_wgs84(self._gs_lat, self._gs_lon, drone.position.x, drone.position.y)
            self.comm_drone_table.setItem(row, 0, QTableWidgetItem(drone.drone_id))
            self.comm_drone_table.setItem(row, 1, QTableWidgetItem(f"{w_lat:.6f}"))
            self.comm_drone_table.setItem(row, 2, QTableWidgetItem(f"{w_lon:.6f}"))
            self.comm_drone_table.setItem(row, 3, QTableWidgetItem(f"{drone.altitude:.1f}"))
            self.comm_drone_table.setItem(row, 4, QTableWidgetItem(f"{drone.current_speed:.1f}"))

    def _tick(self) -> None:
        self.engine.step(self.tick_seconds)
        snap = self.engine.snapshot()
        drones = snap["drones"]
        self.map_canvas.update_state(drones)
        self.time_label.setText(f"System Time: t={snap['time']:.1f}s")
        self._update_status_strip(snap)

        self._refresh_gcs_panels_from_snapshot()

        self.status_table.setRowCount(len(drones))
        for row, drone in enumerate(drones):
            w_lat, w_lon = world_meters_to_wgs84(self._gs_lat, self._gs_lon, drone.position.x, drone.position.y)
            self.status_table.setItem(row, 0, QTableWidgetItem(drone.drone_id))
            self.status_table.setItem(row, 1, QTableWidgetItem(drone.status.value))
            self.status_table.setItem(row, 2, QTableWidgetItem(drone.assigned_slot_id or "-"))
            self.status_table.setItem(row, 3, QTableWidgetItem(f"{drone.altitude:.1f}"))
            self.status_table.setItem(row, 4, QTableWidgetItem(f"({drone.position.x:.1f}, {drone.position.y:.1f})"))
            self.status_table.setItem(row, 5, QTableWidgetItem(f"{w_lat:.6f}"))
            self.status_table.setItem(row, 6, QTableWidgetItem(f"{w_lon:.6f}"))

        self.alert_list.clear()
        for msg in snap["alert_feed"]:
            self.alert_list.addItem(msg)

        self._sync_drone_cards_telemetry()
        self._refresh_stand_cards_state()
        self._process_pilot_deviation_alerts()
        self._refresh_demo_live_narrative()

    def _update_status_strip(self, snap: dict) -> None:
        alerts = len(snap["alert_feed"])
        self.alarm_label.setText(f"Active Alarms: {alerts}")
        self.gps_label.setText("GPS: High")
        self.link_label.setText("Link: Good")
        self.power_label.setText("Power: 78%")
