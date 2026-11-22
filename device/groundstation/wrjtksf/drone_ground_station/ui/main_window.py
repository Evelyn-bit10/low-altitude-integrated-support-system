# ui/main_window.py
"""主窗口UI组件"""
import sys
import os
# 将上级目录加入路径，确保能导入同级的 config、config_stands 等模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import base64
import json
import queue
import re
import time
from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
                             QTextEdit, QGroupBox, QSplitter, QFrame,
                             QScrollArea, QPushButton, QMessageBox, QTabWidget, QLabel, QGridLayout,
                             QComboBox)
from PyQt5.QtCore import QUrl, QObject, pyqtSlot, QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile
from PyQt5.QtWebChannel import QWebChannel

from config import (WINDOW_SIZE, RIGHT_PANEL_MIN_WIDTH, LEFT_RIGHT_SPLIT_RATIO,
                    DEFAULT_DRONES, WEATHER_API_KEY, WEATHER_UPDATE_INTERVAL,
                    DEFAULT_MAP_CENTER, DRONE_SVG_PATH, GROUND_STATION_SVG_PATH,
                    SMTP_ENABLED, SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
                    SMTP_USE_SSL, SMTP_USE_STARTTLS, MAIL_SENDER)
from config_stands import DRONE_STANDS, DRONE_WIND_RESISTANCE
from utils import get_location_sync, wgs84_to_gcj02, get_pi_gps_sync
from api import WeatherManager
from ui.drone_card import DroneInfoCard
from ui.drone_card_stack import DroneCardStack
from ui.pilot_card_stack import PilotCardStack
from ui.stand_card_stack import StandCardStack
from ui.weather_card import WeatherInfoCard
from ui.sensor_card import SensorRealtimeCard
from ui.rid_card import RIDRealtimeCard
from ui.dialogs import AddDroneDialog, PilotInfoDialog
from ui.sim_control_panel import SimControlPanel
from utils.email_sender import EmailSender
from engine.sim_bridge import SimBridge
from engine.coord_bridge import CoordBridge
import yaml
from ui.stand_assign_dialog import StandAssignDialog
from workers import DroneTelemetryWorker
from utils.tile_server import TileServerThread
from radar import RadarWidget
from adsb_reader import (
    ADSBSerialReader,
    BAUD_RATE,
    SERIAL_PORT,
    clear_adsb_cache,
    decode_and_update,
    get_aircraft_snapshot,
)

# 安全导入 pyserial（树莓派可能缺失）
try:
    import serial
    import serial.tools.list_ports
except (ImportError, Exception):
    serial = None


ADSB_TARGET_MAX_AGE_SECONDS = 30

class Bridge(QObject):
    """JavaScript桥接对象"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent

    @pyqtSlot(float, float)
    def updatePosition(self, lat, lng):
        pass

    @pyqtSlot(str)
    def showRidDroneDetail(self, serial_num: str):
        """JS 回调：点击地图上 RID 无人机图标 → 弹出详情窗口"""
        if self.main_window and hasattr(self.main_window, 'rid_card') and self.main_window.rid_card:
            tracker = self.main_window.rid_card.tracker
            if tracker:
                drone = tracker.get(serial_num)
                if drone:
                    self.main_window.rid_card._show_detail_dialog(drone)

    @pyqtSlot()
    def exitAppFullscreen(self):
        """JS 回调：退出整个 PyQt5 窗口的全屏模式"""
        if self.main_window and self.main_window.isFullScreen():
            self.main_window.showNormal()
            self.main_window.activateWindow()
            self.main_window.raise_()


class MapPage(QWebEnginePage):
    """地图页面，用于捕获控制台输出"""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if "there is no texture bound" in message or "WebGL" in message or "gles2_cmd_decoder" in message:
            return
        print(f"JS Console [{lineNumber}]: {message}")


class _RadarPanel(QFrame):
    """左下角 ADS-B 面板。"""
    adsbConnectRequested = pyqtSignal(bool, str)  # (connect: bool, port: str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0f9ff, stop:1 #e6f7ff);
                border: 2px solid #69c0ff;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.title_label = QLabel("ADS-B 50.0 km")
        self.title_label.setStyleSheet("font-size: 14px; color: #003a8c; font-weight: bold; background: transparent;")
        layout.addWidget(self.title_label)

        # ── 串口选择行 ──
        port_row = QHBoxLayout()
        port_row.setSpacing(6)
        port_row.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(100)
        self.port_combo.setStyleSheet("""
            QComboBox {
                padding: 2px 6px; border: 1px solid #dcdfe6; border-radius: 4px;
                background: white; font-size: 11px; color: #303133;
            }
            QComboBox:hover { border-color: #409EFF; }
        """)
        self._refresh_adsb_ports()
        port_row.addWidget(self.port_combo)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("刷新串口列表")
        refresh_btn.setStyleSheet(
            "QPushButton { border: 1px solid #dcdfe6; border-radius: 4px; background: white; font-size: 12px; }"
            "QPushButton:hover { background: #ecf5ff; }")
        refresh_btn.clicked.connect(self._refresh_adsb_ports)
        port_row.addWidget(refresh_btn)

        self.adsb_connect_btn = QPushButton("⚡ 连接")
        self.adsb_connect_btn.setStyleSheet(
            "QPushButton { background-color: #67C23A; color: white; border: none; "
            "border-radius: 4px; padding: 3px 10px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background-color: #85ce61; }")
        self.adsb_connect_btn.clicked.connect(self._toggle_adsb)
        port_row.addWidget(self.adsb_connect_btn)
        port_row.addStretch()
        layout.addLayout(port_row)

        self.adsb_status_label = QLabel("未连接")
        self.adsb_status_label.setStyleSheet(
            "font-size: 10px; color: #8b949e; background: transparent; font-weight: 600;")
        layout.addWidget(self.adsb_status_label)

        self._adsb_connected = False

        # ADS-B 串口自动刷新定时器（与 RID 一致，每 2 秒检测新插入的串口设备）
        self._adsb_port_timer = QTimer(self)
        self._adsb_port_timer.timeout.connect(self._auto_refresh_adsb_ports)
        self._adsb_port_timer.start(4000)

        self.radar_widget = RadarWidget(self)
        self.radar_widget.setMinimumHeight(160)
        layout.addWidget(self.radar_widget, 1)

        self.title_timer = QTimer(self)
        self.title_timer.timeout.connect(self._refresh_title)
        self.title_timer.start(2000)
        self._refresh_title()

    def append(self, text: str):
        if not text:
            return
        if "地面站经纬度" in text:
            lat_match = re.search(r'纬度[=:]\s*([-\d.]+)', text)
            lng_match = re.search(r'经度[=:]\s*([-\d.]+)', text)
            if lat_match and lng_match:
                self.set_center(float(lat_match.group(1)), float(lng_match.group(1)))

    def set_center(self, lat, lng):
        self.radar_widget.set_center(lat, lng)
        self._refresh_title()

    def set_targets(self, targets):
        self.radar_widget.set_targets(targets)
        self._refresh_title()

    def _refresh_title(self):
        range_km = self.radar_widget.calculate_display_range() / 1000.0
        self.title_label.setText(f"ADS-B {range_km:.1f} km")

    def _refresh_adsb_ports(self):
        """刷新 ADS-B 串口下拉列表（手动触发，无去重）。"""
        if serial is None:
            return
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        self.port_combo.addItem("无")
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []
        for p in ports:
            if self.port_combo.findText(p) == -1:
                self.port_combo.addItem(p)
        if current and self.port_combo.findText(current) >= 0:
            self.port_combo.setCurrentText(current)
        elif current == "无" and ports:
            # 之前选了"无"但新检测到串口 → 自动选中第一个
            self.port_combo.setCurrentIndex(1 if self.port_combo.count() > 1 else 0)

    def _auto_refresh_adsb_ports(self):
        """定时自动刷新串口列表（仅当未连接且端口列表有变化时更新）。"""
        if self._adsb_connected:
            return
        if serial is None:
            return
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return
        # 构建现有列表（排除"无"占位项）
        existing = [
            self.port_combo.itemText(i)
            for i in range(self.port_combo.count())
            if self.port_combo.itemText(i) != "无"
        ]
        if set(ports) == set(existing):
            return  # 无变化，不刷新避免闪烁
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        self.port_combo.addItem("无")
        for p in ports:
            self.port_combo.addItem(p)
        if current and current != "无" and current in ports:
            self.port_combo.setCurrentText(current)
        elif ports:
            self.port_combo.setCurrentIndex(1)  # 跳过"无"，选第一个真实串口

    def _get_selected_adsb_port(self) -> str:
        """获取当前选择的 ADS-B 串口，'无'返回空字符串。"""
        t = self.port_combo.currentText().strip()
        return "" if t == "无" else t

    def _toggle_adsb(self):
        """切换 ADS-B 连接状态。"""
        if self._adsb_connected:
            self.adsbConnectRequested.emit(False, "")
        else:
            port = self._get_selected_adsb_port()
            if not port:
                QMessageBox.warning(self, "串口未设置", "请先选择 ADS-B 串口！")
                return
            self.adsbConnectRequested.emit(True, port)

    def set_adsb_status(self, connected: bool, port: str = ""):
        """由 MapWindow 调用来更新 ADS-B 连接状态显示。"""
        self._adsb_connected = connected
        if connected:
            self.adsb_connect_btn.setText("⏹ 断开")
            self.adsb_connect_btn.setStyleSheet(
                "QPushButton { background-color: #F56C6C; color: white; border: none; "
                "border-radius: 4px; padding: 3px 10px; font-weight: bold; font-size: 11px; }"
                "QPushButton:hover { background-color: #f78989; }")
            self.adsb_status_label.setText(f"已连接 {port}")
            self.adsb_status_label.setStyleSheet(
                "font-size: 10px; color: #67C23A; background: transparent; font-weight: 600;")
        else:
            self.adsb_connect_btn.setText("⚡ 连接")
            self.adsb_connect_btn.setStyleSheet(
                "QPushButton { background-color: #67C23A; color: white; border: none; "
                "border-radius: 4px; padding: 3px 10px; font-weight: bold; font-size: 11px; }"
                "QPushButton:hover { background-color: #85ce61; }")
            self.adsb_status_label.setText("未连接")
            self.adsb_status_label.setStyleSheet(
                "font-size: 10px; color: #8b949e; background: transparent; font-weight: 600;")


class _WeatherWorker(QThread):
    """后台线程 + 独立事件循环：天气请求不再阻塞主线程。

    原来 update_weather() 在主线程里 run_until_complete()，天气接口慢或超时
    （还有 2s/4s 退避重试）时整个窗口会「未响应」，连关闭按钮都点不动。
    """
    ready = pyqtSignal(dict)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._queue = queue.Queue()
        self._loop = None

    def request(self, lat, lng):
        self._queue.put((lat, lng))

    def stop(self):
        self._queue.put(None)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                lat, lng = item
                try:
                    data = self._loop.run_until_complete(self._manager.get_weather(lat, lng))
                except Exception:
                    data = {}
                self.ready.emit(data if isinstance(data, dict) else {})
        finally:
            try:
                self._loop.close()
            except Exception:
                pass


class _LocateWorker(QThread):
    """一次性定位任务：WinRT（Windows GPS）在无定位权限时会卡很久，放后台跑。"""
    done = pyqtSignal(object, object, object)

    def run(self):
        lat = lng = source = None
        try:
            lat, lng = get_pi_gps_sync()
            if lat is not None and lng is not None:
                source = "树莓派GPS"
        except Exception:
            pass
        if lat is None or lng is None:
            try:
                lat, lng = get_location_sync()
                if lat is not None and lng is not None:
                    source = "Windows GPS"
            except Exception:
                pass
        self.done.emit(lat, lng, source)


class MapWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("无人机地面站 - 高德地图版")
        self.setGeometry(100, 100, *WINDOW_SIZE)

        self._init_managers()
        self._init_variables()
        self._init_simulation()
        self._init_ui()
        self._init_adsb()
        self._load_map()

    def _init_managers(self):
        # flycontrol occupies 8082; keep the groundstation's local DSM tiles isolated.
        self.tile_server = TileServerThread(port=8081, tile_dir="offline_data/tiles")
        self.tile_server.start()
        self.weather_manager = WeatherManager(
            api_key=WEATHER_API_KEY,
            update_interval=WEATHER_UPDATE_INTERVAL
        )
        self.weather_timer = QTimer()
        self.weather_timer.timeout.connect(self.update_weather)

        self.mailer = None
        try:
            if SMTP_ENABLED and SMTP_SERVER and SMTP_USERNAME and (SMTP_PASSWORD or os.environ.get("SMTP_PASSWORD")):
                self.mailer = EmailSender(
                    smtp_server=SMTP_SERVER,
                    smtp_port=int(SMTP_PORT),
                    username=SMTP_USERNAME,
                    password=SMTP_PASSWORD,
                    use_ssl=bool(SMTP_USE_SSL),
                    use_starttls=bool(SMTP_USE_STARTTLS),
                )
        except Exception as e:
            print(f"[Email] 初始化失败: {e}")

    def _init_variables(self):
        self.current_location = None
        self.radar_targets = {}
        self.adsb_targets = {}
        self.dynamic_drones = []
        self.drone_cards = {}
        self.drone_workers = []
        self.stand_assignments = {}
        self.occupied_stands = set()
        self.last_weather_data = {}
        self._asyncio_loop = None
        self.drone_pilots = {}
        self.adsb_reader = None
        self.is_adsb_connected = False
        self._rid_on_map: set = set()  # 已在地图上绘制的 RID 目标序列号
        self._weather_worker = None
        self._locate_worker = None
        self.sim_bridge = None
        self.sim_control_panel = None
        self._sim_drone_positions: dict = {}  # drone_id -> (lat, lng) for map

    def _init_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("mainCentralWidget")
        central_widget.setAttribute(Qt.WA_StyledBackground, True)
        central_widget.setAutoFillBackground(True)
        self.setCentralWidget(central_widget)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f7fa; }
            QWidget#mainCentralWidget { background-color: #f5f7fa; }
        """)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(5)
        main_layout.addWidget(main_splitter, 1)

        left_splitter = self._create_left_panel()
        main_splitter.addWidget(left_splitter)

        self.right_panel = self._create_right_panel()
        main_splitter.addWidget(self.right_panel)

        main_splitter.setStretchFactor(0, LEFT_RIGHT_SPLIT_RATIO[0])
        main_splitter.setStretchFactor(1, LEFT_RIGHT_SPLIT_RATIO[1])

        self.bridge = Bridge(self)

    def _init_adsb(self):
        self.adsb_timer = QTimer(self)
        self.adsb_timer.timeout.connect(self.refresh_adsb_targets)
        self.adsb_timer.start(2000)
        # 连接 ADS-B 面板的信号
        if hasattr(self.info_display, 'adsbConnectRequested'):
            self.info_display.adsbConnectRequested.connect(self._on_adsb_connect_requested)
        self.refresh_adsb_targets()

    def _on_adsb_connect_requested(self, connect: bool, port: str):
        """处理 ADS-B 面板的连接/断开请求。"""
        if connect:
            self._connect_adsb(port)
        else:
            self._disconnect_adsb()

    def _connect_adsb(self, port: str = ""):
        if not port:
            port = SERIAL_PORT
        try:
            # 树莓派 Linux 下检查串口权限
            import platform
            if platform.system() == "Linux" and not os.path.exists(port):
                self.info_display.append(f"❌ ADS-B 串口不存在: {port}")
                if hasattr(self.info_display, 'set_adsb_status'):
                    self.info_display.set_adsb_status(False)
                return
            self.adsb_reader = ADSBSerialReader(port, BAUD_RATE, decode_and_update)
            if not self.adsb_reader.connect():
                self.adsb_reader = None
                self.is_adsb_connected = False
                if hasattr(self.info_display, 'set_adsb_status'):
                    self.info_display.set_adsb_status(False)
                self.info_display.append(f"❌ ADS-B 连接失败: {port}")
                # Linux 下提示权限问题
                if platform.system() == "Linux":
                    self.info_display.append("💡 Linux提示: 请确认用户已在 dialout 组 (sudo usermod -aG dialout $USER)")
                return
            clear_adsb_cache()
            self.adsb_reader.start_reading()
            self.is_adsb_connected = True
            if hasattr(self.info_display, 'set_adsb_status'):
                self.info_display.set_adsb_status(True, port)
            self.info_display.append(f"✅ ADS-B 已连接: {port}")
            # 启动连接状态监控定时器
            if not hasattr(self, '_adsb_watchdog_timer'):
                self._adsb_watchdog_timer = QTimer(self)
                self._adsb_watchdog_timer.timeout.connect(self._check_adsb_health)
                self._adsb_watchdog_timer.start(5000)
        except Exception as e:
            self.adsb_reader = None
            self.is_adsb_connected = False
            if hasattr(self.info_display, 'set_adsb_status'):
                self.info_display.set_adsb_status(False)
            self.info_display.append(f"❌ ADS-B 连接异常: {e}")
            import traceback
            traceback.print_exc()

    def _disconnect_adsb(self):
        try:
            if hasattr(self, '_adsb_watchdog_timer'):
                self._adsb_watchdog_timer.stop()
            if self.adsb_reader:
                self.adsb_reader.disconnect()
            self.adsb_reader = None
            clear_adsb_cache()
            self.adsb_targets = {}
            self._refresh_radar_targets()
        except Exception:
            pass
        self.is_adsb_connected = False
        if hasattr(self.info_display, 'set_adsb_status'):
            self.info_display.set_adsb_status(False)
        self.info_display.append("🔌 ADS-B 已断开")

    def _check_adsb_health(self):
        """定期检查 ADS-B 连接健康状态，自动重连（带冷却）。"""
        if not self.is_adsb_connected:
            return
        if self.adsb_reader is None:
            self.is_adsb_connected = False
            if hasattr(self.info_display, 'set_adsb_status'):
                self.info_display.set_adsb_status(False)
            self.info_display.append("⚠️ ADS-B 读取线程已意外退出")
        elif not self.adsb_reader.reading:
            # 冷却：距上次重连不满 30 秒则不重连
            now = time.time()
            last_retry = getattr(self, '_adsb_last_retry_time', 0)
            if now - last_retry < 30:
                return
            self._adsb_last_retry_time = now
            self.info_display.append("⚠️ ADS-B 读取已停止，尝试重连...")
            try:
                self.adsb_reader.disconnect()
            except Exception:
                pass
            self._connect_adsb(self.adsb_reader.port)

    def _create_left_panel(self):
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(5)

        self.browser = QWebEngineView()
        self.browser.setPage(MapPage(self.browser))
        self.browser.page().setBackgroundColor(Qt.black)
        self.browser.setStyleSheet("border:1px solid #dcdfe6; border-radius:8px;")
        self.browser.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.browser.setAttribute(Qt.WA_NoSystemBackground, True)

        # 底部区域：横着排两个框（雷达 + 地面站信息）
        self.bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        # 左：雷达框
        self.info_display = _RadarPanel(parent=self.bottom_widget)
        self.info_display.setMinimumWidth(200)
        self.info_display.setMaximumWidth(300)

        # 右：地面站信息框 + 传感器数据（用 TabWidget 整合）
        self.bottom_tab = QTabWidget()
        self.bottom_tab.setStyleSheet("""
            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab { background-color: rgba(255,255,255,0.7); border: 1px solid #91d5ff; border-bottom: none; 
                           border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 5px 10px; 
                           margin-right: 2px; font-size: 12px; font-weight: 600; color: #0050b3; }
            QTabBar::tab:selected { background-color: #e6f7ff; border-bottom: 2px solid #409EFF; }
            QTabBar::tab:hover { background-color: #ecf5ff; }
        """)
        self.bottom_tab.tabBar().setExpanding(False)

        self.weather_card = WeatherInfoCard(parent=self.bottom_tab)
        self.bottom_tab.addTab(self.weather_card, "🌤 气象信息")

        self.sensor_card = SensorRealtimeCard(parent=self.bottom_tab)
        self.bottom_tab.addTab(self.sensor_card, "📡 传感器数据")

        self.rid_card = RIDRealtimeCard(parent=self.bottom_tab)
        self.bottom_tab.addTab(self.rid_card, "🛰 RID探测")

        # 底部面板使用最小高度（允许拖动分隔条调整大小）
        panel_min_height = 260
        panel_max_height = 520
        self.bottom_widget.setMinimumHeight(panel_min_height)
        self.bottom_widget.setMaximumHeight(panel_max_height)
        self.info_display.setMinimumHeight(panel_min_height)
        self.info_display.setMaximumHeight(panel_max_height)
        self.bottom_tab.setMinimumHeight(panel_min_height)
        self.bottom_tab.setMaximumHeight(panel_max_height)

        bottom_layout.addWidget(self.info_display, 0)
        bottom_layout.addWidget(self.bottom_tab, 1)

        map_wrapper = QWidget()
        map_layout = QGridLayout(map_wrapper)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.addWidget(self.browser, 0, 0, 3, 3)

        self.btn_toggle_right = QPushButton("▶")
        self.btn_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right.setFixedSize(24, 60)
        self.btn_toggle_right.setStyleSheet("""
            QPushButton { background-color: rgba(255, 255, 255, 0.9); border: 1px solid #dcdfe6; border-right: none; border-top-left-radius: 8px; border-bottom-left-radius: 8px; color: #606266; font-size: 14px; font-weight: bold; margin-top: 10px; }
            QPushButton:hover { background-color: #ecf5ff; color: #409EFF; }
        """)
        self.btn_toggle_right.clicked.connect(self.toggle_right_panel)
        map_layout.addWidget(self.btn_toggle_right, 0, 2, Qt.AlignTop | Qt.AlignRight)

        self.btn_toggle_bottom = QPushButton("▼")
        self.btn_toggle_bottom.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_bottom.setFixedSize(60, 24)
        self.btn_toggle_bottom.setStyleSheet("""
            QPushButton { background-color: rgba(255, 255, 255, 0.9); border: 1px solid #dcdfe6; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; color: #606266; font-size: 14px; font-weight: bold; margin-left: 10px; }
            QPushButton:hover { background-color: #ecf5ff; color: #409EFF; }
        """)
        self.btn_toggle_bottom.clicked.connect(self.toggle_bottom_panel)
        map_layout.addWidget(self.btn_toggle_bottom, 2, 0, Qt.AlignBottom | Qt.AlignLeft)

        left_splitter.addWidget(map_wrapper)
        left_splitter.addWidget(self.bottom_widget)
        left_splitter.setStretchFactor(0, 9)
        left_splitter.setStretchFactor(1, 1)

        return left_splitter
        
    def _create_right_panel(self):
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setMinimumWidth(RIGHT_PANEL_MIN_WIDTH)
        right_splitter.setHandleWidth(8)
        right_splitter.setStyleSheet("""
            QSplitter::handle { background-color: #ebeef5; margin: 2px 20px; border-radius: 4px; }
            QSplitter::handle:vertical:hover { background-color: #c0c4cc; }
        """)

        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #dcdfe6; border-radius: 8px; background-color: white; }
            QTabBar::tab { background-color: #f5f7fa; border: 1px solid #dcdfe6; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 6px 8px; margin-right: 1px; }
            QTabBar::tab:selected { background-color: white; border-bottom: 2px solid #409EFF; }
            QTabBar::tab:hover { background-color: #ecf5ff; }
        """)
        tab_widget.tabBar().setExpanding(True)
        tab_widget.tabBar().setUsesScrollButtons(False)

        self.pilot_stack = PilotCardStack()
        tab_widget.addTab(self.pilot_stack, "👨‍✈️ 飞手信息")
        self.pilot_stack.pilotUpdated.connect(self.on_pilot_updated_from_panel)
        self.pilot_stack.pilotViewRequested.connect(self._on_pilot_view_requested)
        self.pilot_stack.currentCardChanged.connect(self._on_pilot_page_changed)

        self.stand_stack = StandCardStack()
        self.stand_stack.standReleased.connect(self.on_stand_released)
        
        self.stand_panel_widget = QWidget()
        stand_layout = QVBoxLayout(self.stand_panel_widget)
        stand_layout.setContentsMargins(5, 5, 5, 5)

        stand_toolbar = QHBoxLayout()
        self.add_stand_btn = QPushButton("➕ 添加机位")
        self.add_stand_btn.setStyleSheet(
            "QPushButton { background-color: #409EFF; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-size: 13px; font-weight: bold; min-width: 90px; } "
            "QPushButton:hover { background-color: #66b1ff; }"
        )
        self.add_stand_btn.clicked.connect(self.show_add_stand_dialog)
        stand_toolbar.addWidget(self.add_stand_btn)
        stand_toolbar.addStretch()

        stand_layout.addLayout(stand_toolbar)
        stand_layout.addWidget(self.stand_stack)

        self._init_stand_cards()
        drone_panel = self._create_drone_panel()
        
        tab_widget.removeTab(tab_widget.indexOf(self.pilot_stack))
        tab_widget.addTab(drone_panel, "✈️ 无人机")
        tab_widget.addTab(self.pilot_stack, "👨‍✈️ 飞手信息")
        tab_widget.addTab(self.stand_panel_widget, "📍 机位管理")

        # 仿真控制面板标签
        if self.sim_control_panel:
            tab_widget.addTab(self.sim_control_panel, "🤖 仿真")

        tab_widget.currentChanged.connect(self._on_tab_changed)

        right_splitter.addWidget(tab_widget)
        right_splitter.setCollapsible(0, False)

        return right_splitter

    def _on_pilot_page_changed(self, drone_id):
        self.current_visible_drone_id = drone_id

    def _on_tab_changed(self, index):
        """当点击上方标签页时，强制把底下的面板同步到当前无人机"""
        drone_id = getattr(self, "current_visible_drone_id", None)
        if not drone_id:
            if self.drone_cards:
                drone_id = list(self.drone_cards.keys())[0]
            else:
                return
                
        if index == 0:  
            if hasattr(self, 'card_stack'):
                if self.card_stack.get_current_card_id() != drone_id:
                    self.card_stack.show_card(drone_id)
                    
        elif index == 1:  
            if hasattr(self, 'pilot_stack') and drone_id in self.pilot_stack.cards:
                if self.pilot_stack.get_current_card_id() != drone_id:
                    self.pilot_stack.show_card(drone_id)
                    
        elif index == 2:  
            if hasattr(self, 'stand_stack'):
                assigned_stand = self.stand_assignments.get(str(drone_id))
                if assigned_stand and "id" in assigned_stand:
                    stand_id = assigned_stand["id"]
                    if hasattr(self.stand_stack, "show_card"):
                        if self.stand_stack.get_current_card_id() != stand_id:
                            self.stand_stack.show_card(stand_id)
                else:
                    if hasattr(self.stand_stack, "card_ids"):
                        curr_stand_id = self.stand_stack.get_current_card_id()
                        if curr_stand_id and curr_stand_id not in self.occupied_stands:
                            pass 
                        else:
                            for sid in self.stand_stack.card_ids:
                                if getattr(self, "occupied_stands", None) is not None and sid not in self.occupied_stands:
                                    self.stand_stack.show_card(sid)
                                    break
                            else:
                                if len(self.stand_stack.card_ids) > 0:
                                    self.stand_stack.show_card_at_index(0)

    def _create_drone_panel(self):
        self.drone_cards_panel = QGroupBox("实时遥测信息 (WGS84)")
        self.drone_cards_panel.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 8px; margin-top: 15px; font-size: 16px; color: #303133; background-color: #f8f9fa; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 8px; }
        """)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.add_drone_btn = QPushButton("➕ 添加无人机")
        self.add_drone_btn.setStyleSheet(
            "QPushButton { background-color: #409EFF; color: white; border: none; border-radius: 4px; padding: 6px 10px; font-size: 13px; font-weight: bold; min-width: 105px; } "
            "QPushButton:hover { background-color: #66b1ff; }")
        self.add_drone_btn.clicked.connect(self.show_add_drone_dialog)
        toolbar_layout.addWidget(self.add_drone_btn)

        self.smart_assign_btn = QPushButton("🤖 智能分配")
        self.smart_assign_btn.setStyleSheet(
            "QPushButton { background-color: #67C23A; color: white; border: none; border-radius: 4px; padding: 6px 10px; font-size: 13px; font-weight: bold; min-width: 95px; } "
            "QPushButton:hover { background-color: #85ce61; }")
        self.smart_assign_btn.clicked.connect(self.smart_assign_all_drones)
        toolbar_layout.addWidget(self.smart_assign_btn)

        toolbar_layout.addStretch()

        self.card_stack = DroneCardStack()
        self.card_stack.currentDroneChanged.connect(self._on_current_drone_changed)

        for drone_config in DEFAULT_DRONES:
            self.add_drone_card(drone_config)

        panel_layout = QVBoxLayout(self.drone_cards_panel)
        panel_layout.addLayout(toolbar_layout)
        panel_layout.addWidget(self.card_stack)
        panel_layout.setContentsMargins(5, 5, 5, 5)

        return self.drone_cards_panel

    def _init_simulation(self):
        """初始化仿真引擎、桥接层和控制面板。
        任何异常都不应阻断主窗口启动，只打印错误并让 sim_bridge 保持 None。"""
        try:
            self._init_simulation_impl()
        except Exception as e:
            import traceback
            print(f"[Sim] 仿真初始化失败: {e}")
            traceback.print_exc()
            self.sim_bridge = None
            self.sim_control_panel = None

    def _init_simulation_impl(self):
        # 尝试加载 demo_config.yaml
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "demo_config.yaml"
        )
        if not os.path.exists(config_path):
            print("[Sim] 未找到 demo_config.yaml，仿真功能不可用")
            return

        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # 使用配置中的 GCS 坐标创建坐标桥接
        gcs_cfg = cfg.get("gcs", {})
        coord = CoordBridge(
            gcs_lat=gcs_cfg.get("default_lat", 29.755),
            gcs_lon=gcs_cfg.get("default_lon", 106.815),
        )

        # 创建仿真桥接
        self.sim_bridge = SimBridge.from_config(cfg, coord=coord)

        # 连接仿真桥接信号
        self.sim_bridge.telemetryUpdated.connect(self.on_sim_telemetry)
        self.sim_bridge.routeUpdated.connect(self.on_sim_route_updated)
        self.sim_bridge.simStatusChanged.connect(self._on_sim_status_changed)
        self.sim_bridge.simDroneListChanged.connect(self._on_sim_drone_list_changed)
        self.sim_bridge.simTimeChanged.connect(self._on_sim_time_changed)
        self.sim_bridge.simAlertAdded.connect(self._on_sim_alert_added)
        self.sim_bridge.simSlotChanged.connect(self._on_sim_slot_changed)

        # 创建控制面板
        self.sim_control_panel = SimControlPanel()
        self.sim_control_panel.scenarioRequested.connect(self._on_sim_scenario)
        self.sim_control_panel.startRequested.connect(self.sim_bridge.start)
        self.sim_control_panel.pauseRequested.connect(self.sim_bridge.pause)
        self.sim_control_panel.stopRequested.connect(self.sim_bridge.stop)
        self.sim_control_panel.resetRequested.connect(self.sim_bridge.reset)
        self.sim_control_panel.speedChanged.connect(self.sim_bridge.set_speed)
        self.sim_control_panel.droneDeviateRequested.connect(self.sim_bridge.set_drone_deviate)
        self.sim_control_panel.droneRecoverRequested.connect(self.sim_bridge.set_drone_recover)
        self.sim_control_panel.droneFollowRequested.connect(self.sim_bridge.set_drone_follow)

        # 保存配置引用，供 _push_sim_zones_to_map 使用
        self._sim_cfg = cfg

        # 保存原始地面站坐标，供虚拟 GCS 还原使用
        self._orig_gcs_lat = gcs_cfg.get("default_lat", 29.755)
        self._orig_gcs_lon = gcs_cfg.get("default_lon", 106.815)
        if self.sim_control_panel:
            self.sim_control_panel.set_gcs_coords(self._orig_gcs_lat, self._orig_gcs_lon)

        # 连接虚拟地面站信号
        self.sim_control_panel.virtualGcsChanged.connect(self._on_virtual_gcs_changed)

        print("[Sim] 仿真引擎已初始化")

    # ------------------------------------------------------------------
    # 仿真信号处理
    # ------------------------------------------------------------------

    def on_sim_telemetry(self, telem: dict):
        """处理仿真无人机遥测 — 复用现有 drone 卡片和地图渲染。"""
        drone_id = str(telem.get("id", "sim-1"))
        lat = telem.get("lat")
        lng = telem.get("lng")
        alt = telem.get("alt")
        battery = telem.get("battery")

        # 确保有对应的 drone 卡片
        if drone_id not in self.drone_cards:
            self._create_sim_drone_card(drone_id, telem.get("name", drone_id))

        if drone_id in self.drone_cards:
            self.drone_cards[drone_id].update_data(lat, lng, alt, battery, 16)
            self.drone_cards[drone_id].set_connected(True)

        # 更新雷达目标
        if lat is not None and lng is not None:
            self.radar_targets[drone_id] = {
                "lat": lat,
                "lon": lng,
                "name": telem.get("name", drone_id),
            }
            self._refresh_radar_targets()

        # 更新 Leaflet 地图上的无人机图标
        if lat is not None and lng is not None:
            gcj_lat, gcj_lng = wgs84_to_gcj02(lat, lng)
            alt_js = "null" if alt is None else float(alt)
            battery_js = "null" if battery is None else float(battery)

            safe_url = "file:///" + DRONE_SVG_PATH.replace("\\", "/")
            icon_html = (
                f"<img src='{safe_url}' style='width:36px; height:36px; "
                f"filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5)); display:block;'>"
            )
            js_code = f"""
            if (typeof updateDroneMulti === 'function') {{
                updateDroneMulti("{drone_id}", {gcj_lat}, {gcj_lng}, {alt_js},
                                {battery_js}, 16.0,
                                {{name: "{drone_id}", emoji: "{icon_html}"}} );
            }}
            """
            self.browser.page().runJavaScript(js_code)
            self._sim_drone_positions[drone_id] = (gcj_lat, gcj_lng)

    def _create_sim_drone_card(self, drone_id: str, name: str):
        """为仿真无人机创建遥测卡片和虚拟飞手信息。"""
        card = DroneInfoCard({"id": drone_id, "name": name, "emoji": "🤖", "model": "仿真无人机", "port": "SIM", "baud": 0})
        card.assignStandClicked.connect(self.show_stand_assign_dialog)
        card.pilotInfoClicked.connect(self.show_pilot_info_dialog)
        self.card_stack.add_card(drone_id, card)
        self.drone_cards[drone_id] = card

        # 同步生成虚拟飞手信息
        if drone_id not in self.drone_pilots:
            import random
            surnames = ["张", "王", "李", "赵", "陈", "刘", "杨", "黄", "周", "吴"]
            given_names = ["建国", "志强", "伟明", "晓峰", "宇航", "浩然", "子涵", "一鸣", "天宇", "博文"]
            pilot_name = random.choice(surnames) + random.choice(given_names)
            pilot_email = f"pilot_{drone_id.lower()}@sim.com"
            pilot_phone = f"138{random.randint(10000000, 99999999)}"
            self.drone_pilots[drone_id] = {
                "name": pilot_name,
                "email": pilot_email,
                "phone": pilot_phone,
            }

        # 同步添加到飞手卡片面板
        try:
            if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                self.pilot_stack.upsert_row(
                    drone_id=drone_id,
                    drone_name=name,
                    pilot=self.drone_pilots.get(drone_id, {})
                )
        except Exception as e:
            pass

    def on_sim_route_updated(self, drone_id: str, pts: list):
        """在 Leaflet 地图上绘制仿真航线。"""
        if not pts:
            return
        pts_json = json.dumps(pts)
        js_code = f"""
        if (typeof drawSimRoute === 'function') {{
            drawSimRoute("{drone_id}", {pts_json});
        }}
        """
        self.browser.page().runJavaScript(js_code)

    def _on_sim_status_changed(self, status: str):
        if self.sim_control_panel:
            if status == "running":
                self.sim_control_panel.set_running(True)
                self.sim_control_panel.set_paused(False)
            elif status == "paused":
                self.sim_control_panel.set_running(True)
                self.sim_control_panel.set_paused(True)
            elif status == "stopped":
                self.sim_control_panel.set_running(False)
                self.sim_control_panel.set_paused(False)
                self.sim_control_panel.clear_alerts()
                # 清理仿真无人机的 Leaflet 标记及卡片
                for did in list(self._sim_drone_positions.keys()):
                    self.browser.page().runJavaScript(
                        f'if(typeof removeSimDrone === "function") removeSimDrone("{did}");'
                    )
                    self._sim_drone_positions.pop(did, None)
                    if did in self.radar_targets:
                        del self.radar_targets[did]
                    if did in self.drone_cards:
                        self.card_stack.remove_card(did)
                        del self.drone_cards[did]
                    # 同步清理虚拟飞手信息
                    if did in self.drone_pilots:
                        del self.drone_pilots[did]
                    if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                        try:
                            self.pilot_stack.remove_row(did)
                        except Exception:
                            pass
                self._refresh_radar_targets()
                # 清理仿真注入的区域（禁飞区/障碍物/机位等）
                self._clear_sim_zones()

    def _on_sim_drone_list_changed(self, drones: list):
        if self.sim_control_panel:
            self.sim_control_panel.update_drone_list(drones)

    def _on_sim_time_changed(self, sim_time: float):
        if self.sim_control_panel:
            self.sim_control_panel.set_time(sim_time)

    def _on_sim_alert_added(self, message: str):
        if self.sim_control_panel:
            self.sim_control_panel.add_alert(message)

    def _on_sim_slot_changed(self, slots: list):
        """仿真机位状态变化时同步到 stand 卡片。"""
        for s in slots:
            sid = s["id"]
            if sid in self.stand_stack.cards:
                card = self.stand_stack.cards[sid]
                if s.get("occupied_by"):
                    card.set_occupied(s["occupied_by"])
                else:
                    card.set_occupied(None)

    def _on_sim_scenario(self, index: int):
        """加载仿真演示场景。"""
        if self.sim_bridge:
            self.sim_bridge.load_scenario(index)
            self.sim_bridge.start()
            # 重新推送仿真区域到地图（stop 时已被 _clear_sim_zones 清理）
            QTimer.singleShot(800, self._push_sim_zones_to_map)

    def _on_virtual_gcs_changed(self, enabled: bool, lat: float, lng: float):
        """虚拟地面站定位切换 — 同步更新仿真坐标、地图地面站标记、定位面板。"""
        if not self.sim_bridge:
            return
        if enabled:
            self.sim_bridge._coord.gcs_lat = lat
            self.sim_bridge._coord.gcs_lon = lng
        else:
            self.sim_bridge._coord.gcs_lat = getattr(self, "_orig_gcs_lat", 29.755)
            self.sim_bridge._coord.gcs_lon = getattr(self, "_orig_gcs_lon", 106.815)

        # 同步更新地图上的地面站标记（"返回地面站"按钮以此为锚点）
        lat_wgs84 = self.sim_bridge._coord.gcs_lat
        lng_wgs84 = self.sim_bridge._coord.gcs_lon
        self.current_location = (lat_wgs84, lng_wgs84)
        self._update_ground_station_panel(lat_wgs84, lng_wgs84)

        lat_gcj, lng_gcj = wgs84_to_gcj02(lat_wgs84, lng_wgs84)

        # 准备地面站图标
        marker_icon = "🏠"
        try:
            import base64
            if os.path.exists(GROUND_STATION_SVG_PATH):
                with open(GROUND_STATION_SVG_PATH, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(GROUND_STATION_SVG_PATH)[1].lower()
                mime_type = "image/svg+xml" if ext == ".svg" else f"image/{ext.strip('.')}"
                safe_url = f"data:{mime_type};base64,{b64_data}"
                marker_icon = f"<img src='{safe_url}' style='width:36px; height:36px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5)); display:block;'>"
        except Exception:
            pass

        js_code = f"""
        (function() {{
            // 移动地面站标记（"返回地面站"按钮的锚点）
            if (typeof updateGroundStation === 'function') {{
                updateGroundStation({lat_gcj}, {lng_gcj}, {{ markerIcon: "{marker_icon}" }});
            }}
            // 同步更新左上角经纬度定位面板的输入框
            var clat = document.getElementById('coordLat');
            var clng = document.getElementById('coordLng');
            if (clat) clat.value = '{lat_gcj:.6f}';
            if (clng) clng.value = '{lng_gcj:.6f}';
        }})();
        """
        self.browser.page().runJavaScript(js_code)

        # 清除旧仿真区域，重新按新坐标推送
        self._clear_sim_zones()
        QTimer.singleShot(300, self._push_sim_zones_to_map)

    # ------------------------------------------------------------------
    # 仿真区域 → 地图区域系统
    # ------------------------------------------------------------------

    def _push_sim_zones_to_map(self):
        """将 demo_config.yaml 的所有区域推送到 Leaflet 区域系统。
        映射：障碍物→obstacle, 禁飞区→nofly, 机位→landing, waiting/pad→custom"""
        if not hasattr(self, "browser") or self.browser is None:
            return
        cfg = getattr(self, "_sim_cfg", None)
        if not cfg:
            return
        coord = self.sim_bridge._coord if self.sim_bridge else CoordBridge()

        from engine.sim_models import Vec2

        # ── 禁飞区 (矩形) → nofly ──
        for nf in cfg.get("no_fly_zones", []):
            sw_lat, sw_lng = coord.vec2_to_gcj02(Vec2(nf.get("x_min", 0), nf.get("y_min", 0)))
            ne_lat, ne_lng = coord.vec2_to_gcj02(Vec2(nf.get("x_max", 10), nf.get("y_max", 10)))
            nf_name = nf.get("name", "禁飞区")
            # 矩形 shape: south=min(sw_lat,ne_lat), west=min(sw_lng,ne_lng), north=max(...), east=max(...)
            self._js_add_zone(
                f"sim-nofly-{nf_name}", nf_name, "nofly",
                rect_shapes=[(sw_lat, sw_lng, ne_lat, ne_lng)],
            )

        # ── 障碍物 (圆形) → obstacle ──
        for obs in cfg.get("obstacles", []):
            clat, clng = coord.vec2_to_gcj02(Vec2(obs.get("x", 0), obs.get("y", 0)))
            obs_name = obs.get("name", "障碍物")
            h = obs.get("height", 0)
            label = f"{obs_name} H={h}m"
            self._js_add_zone(
                f"sim-obs-{obs_name}", label, "obstacle",
                circle_shapes=[(clat, clng, obs.get("radius", 8))],
            )

        # ── 机位 (圆形) → landing ──
        for s in cfg.get("slots", []):
            clat, clng = coord.vec2_to_gcj02(Vec2(s.get("x", 0), s.get("y", 0)))
            sid = s.get("id", "?")
            sn = s.get("name", sid)
            r = s.get("footprint_radius_m", 13)
            self._js_add_zone(
                f"sim-land-{sid}", sn, "landing",
                circle_shapes=[(clat, clng, r)],
            )

        # ── zones.waiting → custom(蓝), zones.pad → landing(绿) ──
        zones_map = cfg.get("zones", {})
        for zone_key, label, ztype in [("waiting", "等待区", "custom"), ("pad", "停机坪", "landing")]:
            zc = zones_map.get(zone_key, {})
            if not zc:
                continue
            sw_lat, sw_lng = coord.vec2_to_gcj02(Vec2(zc.get("x_min", 0), zc.get("y_min", 0)))
            ne_lat, ne_lng = coord.vec2_to_gcj02(Vec2(zc.get("x_max", 10), zc.get("y_max", 10)))
            self._js_add_zone(
                f"sim-{ztype}-{zone_key}", label, ztype,
                rect_shapes=[(sw_lat, sw_lng, ne_lat, ne_lng)],
            )

    def _clear_sim_zones(self):
        """删除所有 sim- 前缀的区域（仿真停止时调用）。"""
        if not hasattr(self, "browser") or self.browser is None:
            return
        js = """
        (function() {
            if (!window.zones) return;
            var removed = [];
            Object.keys(window.zones).forEach(function(id) {
                if (id.indexOf('sim-') === 0) {
                    removed.push(id);
                }
            });
            removed.forEach(function(id) {
                var z = window.zones[id];
                if (z && z._layers) {
                    z._layers.forEach(function(l) {
                        if (window.zonesLayerGroup) window.zonesLayerGroup.removeLayer(l);
                    });
                }
                delete window.zones[id];
            });
            if (window.saveZonesToStorage) window.saveZonesToStorage();
            if (window.refreshZoneList) window.refreshZoneList();
        })();
        """
        try:
            self.browser.page().runJavaScript(js)
        except Exception:
            pass

    def _js_add_zone(self, zone_id: str, name: str, zone_type: str,
                     rect_shapes=None, circle_shapes=None):
        """通过 runJavaScript 直接注入一个区域到 Leaflet 地图的区域系统。

        rect_shapes:  [(sw_lat, sw_lng, ne_lat, ne_lng), ...]
        circle_shapes: [(centerLat, centerLng, radiusM), ...]
        """
        if not hasattr(self, "browser") or self.browser is None:
            return
        shapes_js = []
        for r in (rect_shapes or []):
            sw_lat, sw_lng, ne_lat, ne_lng = r[0], r[1], r[2], r[3]
            # renderZone 期望: {type:"rect", south, west, north, east, rotation}
            south = min(sw_lat, ne_lat)
            north = max(sw_lat, ne_lat)
            west = min(sw_lng, ne_lng)
            east = max(sw_lng, ne_lng)
            shapes_js.append(
                f'{{type:"rect",south:{south},west:{west},north:{north},east:{east},rotation:0}}'
            )
        for c in (circle_shapes or []):
            # renderZone 期望: {type:"circle", centerLat, centerLng, radiusM}
            shapes_js.append(
                f'{{type:"circle",centerLat:{c[0]},centerLng:{c[1]},radiusM:{c[2]}}}'
            )
        shapes_str = "[" + ",".join(shapes_js) + "]"

        js = f"""
        (function _addSimZone(retry) {{
            retry = retry || 0;
            if (window.zones && window.renderZone) {{
                var zone = {{
                    id: "{zone_id}",
                    name: "{name}",
                    type: "{zone_type}",
                    shapes: {shapes_str},
                    visible: true
                }};
                window.zones["{zone_id}"] = zone;
                window.renderZone(zone);
                if (window.saveZonesToStorage) window.saveZonesToStorage();
                if (window.refreshZoneList) window.refreshZoneList();
            }} else if (retry < 10) {{
                setTimeout(function() {{ _addSimZone(retry + 1); }}, 500);
            }}
        }})();
        """
        try:
            self.browser.page().runJavaScript(js)
        except Exception:
            pass  # 页面未就绪时忽略

    def _load_map(self):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(current_dir, "web", "map.html")

        if not os.path.exists(html_path):
            self.info_display.append(f"❌ 错误: 找不到地图文件: {html_path}")
            return

        # 保留 WebEngine 磁盘缓存：高德瓦片缓存后二次启动明显更快。
        # map.html 本身用 URL 上的 _t= 时间戳绕过缓存，既能拿到最新页面，又不用每次重下瓦片。
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.browser.page().setWebChannel(self.channel)

        # 在页面加载前注入默认地图中心（config.py 中 DEFAULT_MAP_CENTER）
        default_lat, default_lng = DEFAULT_MAP_CENTER
        inject_js = f"window.defaultCenter = {{lng: {default_lng}, lat: {default_lat}}};"
        self.browser.page().loadFinished.connect(self._on_map_loaded)
        # 添加时间戳参数防缓存
        import time
        url = QUrl.fromLocalFile(html_path)
        url.setQuery("_t=" + str(int(time.time())))
        self.browser.setUrl(url)
        self.browser.page().runJavaScript(inject_js)

    def _on_map_loaded(self, ok):
        if ok:
            self.info_display.append("✅ 地图加载成功，正在获取位置...")
            QTimer.singleShot(1000, self.get_location_and_update_map)
            # 定期刷新位置（30秒），用于 GPS/传感器数据到位后自动切换定位源
            self._pos_refresh_timer = QTimer(self)
            self._pos_refresh_timer.timeout.connect(self._periodic_position_refresh)
            self._pos_refresh_timer.start(30000)
            # 定期同步 RID 探测无人机到地图（每 2 秒）
            self._rid_sync_timer = QTimer(self)
            self._rid_sync_timer.timeout.connect(self._sync_rid_drones_to_map)
            self._rid_sync_timer.start(3000)
            # 推出仿真配置中的障碍物和禁飞区到地图区域系统
            QTimer.singleShot(2000, self._push_sim_zones_to_map)
        else:
            self.info_display.append("❌ 地图加载失败")

    def _periodic_position_refresh(self):
        """定期检查是否有更好的定位源可用（复用后台定位，不阻塞 UI）。"""
        if self.current_location and self.current_location != DEFAULT_MAP_CENTER:
            return  # 已有有效位置（非默认值），不必刷新
        self.get_location_and_update_map()

    def _sync_rid_drones_to_map(self):
        """定期将 RID 探测到的无人机同步到地图上。"""
        if not hasattr(self, 'rid_card') or not self.rid_card:
            return
        if not self.rid_card.tracker:
            return
        drones = self.rid_card.tracker.get_all()
        # 从地图上移除已不在线 (tracker 超时) 的目标
        online_serials = {d.drone_serial_num for d in drones}
        stale = [s for s in self._rid_on_map if s not in online_serials]
        for s in stale:
            js = f"if(typeof removeRidDrone==='function'){{removeRidDrone('{s}');}}"
            self.browser.page().runJavaScript(js)
            self._rid_on_map.discard(s)

        for d in drones:
            if not d.drone_latitude or not d.drone_longitude:
                continue
            lat_gcj, lng_gcj = wgs84_to_gcj02(d.drone_latitude, d.drone_longitude)
            is_new = d.drone_serial_num not in self._rid_on_map
            js = (
                f"if(typeof updateRidDrone==='function'){{"
                f"updateRidDrone('{d.drone_serial_num}', {lat_gcj}, {lng_gcj}, "
                f"{d.height or 0}, {d.speed_kmh}, '{d.heading_str}', "
                f"'{d.product_type_str}', {d.drone_type}, {str(is_new).lower()});"
                f"}}"
            )
            self.browser.page().runJavaScript(js)
            self._rid_on_map.add(d.drone_serial_num)

        # 清理 JS 端的过期标记（60秒未更新）
        js_cleanup = "if(typeof cleanupStaleRidDrones==='function'){cleanupStaleRidDrones(60000);}"
        self.browser.page().runJavaScript(js_cleanup)

    def toggle_right_panel(self):
        if hasattr(self, 'right_panel'):
            is_visible = self.right_panel.isVisible()
            self.right_panel.setVisible(not is_visible)
            self.btn_toggle_right.setText("◀" if is_visible else "▶")

    def toggle_bottom_panel(self):
        if hasattr(self, 'bottom_widget'):
            is_visible = self.bottom_widget.isVisible()
            self.bottom_widget.setVisible(not is_visible)
            self.btn_toggle_bottom.setText("▲" if is_visible else "▼")

    # ==================== 机位管理相关 ====================
    def _init_stand_cards(self):
        """初始化机位卡片"""
        from utils.stand_store import list_stands
        from ui.stand_card import StandInfoCard

        stands = list_stands()
        for stand_info in stands:
            stand_id = stand_info.get("id")
            if not stand_id:
                continue
            stand_name = stand_info.get("name", stand_id)
            stand_type = stand_info.get("type", "outdoor")

            card = StandInfoCard(stand_id, stand_name, stand_type)
            card.releaseStandClicked.connect(lambda sid: self.stand_stack.standReleased.emit(sid))
            card.deleteStandClicked.connect(self.remove_stand) 
            card.editStandClicked.connect(self.edit_stand)     
            
            self.stand_stack.add_card(stand_id, card)
            self.stand_stack.stand_details[stand_id] = stand_info
            card._stand_name = stand_name
            card._is_occupied = False

    def show_add_stand_dialog(self):
        """显示添加机位的弹窗并处理返回结果"""
        from ui.dialogs import AddStandDialog
        
        existing_stands = self.stand_stack.stand_details if hasattr(self.stand_stack, "stand_details") else {}
        dialog = AddStandDialog(existing_stands, self)
        
        if dialog.exec_() == dialog.Accepted:
            stand_data = dialog.get_data()
            stand_id = stand_data["id"]
            
            from ui.stand_card import StandInfoCard
            card = StandInfoCard(stand_id, stand_data["name"], stand_data["type"])
            card.releaseStandClicked.connect(lambda sid: self.stand_stack.standReleased.emit(sid))
            card.deleteStandClicked.connect(self.remove_stand) 
            card.editStandClicked.connect(self.edit_stand)     
            
            self.stand_stack.add_card(stand_id, card)
            self.stand_stack.stand_details[stand_id] = stand_data
            card._stand_name = stand_data["name"]
            card._is_occupied = False
            
            self.info_display.append(f"📍 已成功添加机位: {stand_data['name']} (ID: {stand_id})")

    def remove_stand(self, stand_id: str):
        """删除机位"""
        if stand_id in self.occupied_stands:
            QMessageBox.warning(self, "无法移除", f"机位【{stand_id}】当前正被占用！\n请先释放该机位，然后再执行删除。")
            return

        stand_name = self.stand_stack.stand_details.get(stand_id, {}).get("name", stand_id)
        
        msg = QMessageBox(self)
        msg.setWindowTitle("确认移除")
        msg.setText(f"确定要永久移除机位【{stand_name}】吗？")
        msg.setIcon(QMessageBox.Warning)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)

        yes_btn = msg.button(QMessageBox.Yes)
        no_btn = msg.button(QMessageBox.No)
        if yes_btn: yes_btn.setStyleSheet("QPushButton { background-color: #F56C6C; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; } QPushButton:hover { background-color: #f78989; }")
        if no_btn: no_btn.setStyleSheet("QPushButton { background-color: #909399; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; } QPushButton:hover { background-color: #a6a9ad; }")

        if msg.exec_() == QMessageBox.Yes:
            self.stand_stack.remove_card(stand_id)
            if stand_id in self.stand_stack.stand_details:
                del self.stand_stack.stand_details[stand_id]
            self.info_display.append(f"🗑️ 已移除机位: {stand_name} (ID: {stand_id})")

    def edit_stand(self, stand_id: str):
        """编辑机位信息"""
        from ui.dialogs import AddStandDialog
        
        existing_stands = self.stand_stack.stand_details if hasattr(self.stand_stack, "stand_details") else {}
        current_data = existing_stands.get(stand_id, {})

        dialog = AddStandDialog(existing_stands, edit_mode=True, current_data=current_data, parent=self)
        
        if dialog.exec_() == dialog.Accepted:
            stand_data = dialog.get_data()
            
            if hasattr(self.stand_stack, "cards") and stand_id in self.stand_stack.cards:
                card = self.stand_stack.cards[stand_id]
                card.name = stand_data["name"]
                card.stand_type = stand_data["type"]
                card._apply_static_content()
                card._stand_name = stand_data["name"]
                
            self.stand_stack.stand_details[stand_id] = stand_data
            
            for d_id, s_info in self.stand_assignments.items():
                if s_info["id"] == stand_id:
                    self.stand_assignments[d_id]["name"] = stand_data["name"]
                    self.stand_assignments[d_id]["type"] = stand_data["type"]
                    if d_id in self.drone_cards:
                        self.drone_cards[d_id].set_assigned_stand(stand_id, self.stand_assignments[d_id])
            
            self.info_display.append(f"📝 已更新机位信息: {stand_data['name']} (ID: {stand_id})")

    # ==================== 无人机管理相关 ====================
    def _on_current_drone_changed(self, drone_id):
        self.current_visible_drone_id = drone_id 
        
        if hasattr(self, 'pilot_stack') and drone_id in self.pilot_stack.cards:
            if self.pilot_stack.get_current_card_id() != drone_id:
                self.pilot_stack.show_card(drone_id)

        if hasattr(self, 'stand_stack'):
            assigned_stand = self.stand_assignments.get(str(drone_id))
            if assigned_stand and "id" in assigned_stand:
                stand_id = assigned_stand["id"]
                if hasattr(self.stand_stack, "show_card"):
                    if self.stand_stack.get_current_card_id() != stand_id:
                        self.stand_stack.show_card(stand_id)
            else:
                if hasattr(self.stand_stack, "card_ids"):
                    curr_stand_id = self.stand_stack.get_current_card_id()
                    if curr_stand_id and curr_stand_id not in self.occupied_stands:
                        pass
                    else:
                        for sid in self.stand_stack.card_ids:
                            if getattr(self, "occupied_stands", None) is not None and sid not in self.occupied_stands:
                                self.stand_stack.show_card(sid)
                                break
                        else:
                            if len(self.stand_stack.card_ids) > 0:
                                self.stand_stack.show_card_at_index(0)
            
    def add_drone_card(self, drone_config):
        if "model" not in drone_config:
            drone_config["model"] = "自定义无人机"

        card = DroneInfoCard(drone_config)
        card.removeClicked.connect(self.remove_drone)
        card.connectClicked.connect(self.on_drone_connect_clicked)
        card.assignStandClicked.connect(self.show_stand_assign_dialog)
        card.releaseStandClicked.connect(self.release_stand)
        card.pilotInfoClicked.connect(self.show_pilot_info_dialog)

        drone_id = str(drone_config["id"])
        self.card_stack.add_card(drone_id, card)
        self.drone_cards[drone_id] = card

        pilot = drone_config.get("pilot") or {}
        self.drone_pilots[drone_id] = {
            "name": pilot.get("name", ""),
            "email": pilot.get("email", ""),
            "phone": pilot.get("phone", ""),
        }

        worker = DroneTelemetryWorker(
            drone_id=drone_id,
            drone_name=drone_config.get("name", f'无人机 {drone_config.get("id")}'),
            drone_emoji=drone_config.get("emoji", "🚁"),
            serial_port=drone_config.get("port"),
            baudrate=int(drone_config.get("baud", 57600)),
            parent=self
        )
        worker.statusUpdated.connect(self.on_drone_status)
        worker.telemetryUpdated.connect(self.on_drone_telemetry)
        worker.connectionChanged.connect(self.on_drone_connection_changed)
        self.drone_workers.append(worker)
        worker.start()

        self.info_display.append(f"✅ 已添加无人机: {drone_config['name']} (ID: {drone_config['id']})")

        try:
            if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                self.pilot_stack.upsert_row(
                    drone_id=drone_id,
                    drone_name=drone_config.get("name", f'无人机 {drone_config.get("id")}'),
                    pilot=self.drone_pilots.get(drone_id, {}) or {}
                )
        except Exception as e:
            pass

    def remove_drone(self, drone_id):
        """移除无人机卡片及其相关资源（安全版，防止程序崩溃）"""
        
        # 🚀 核心新增：如果无人机已经分配了机位，严格拦截删除操作！
        if hasattr(self, "stand_assignments") and drone_id in self.stand_assignments:
            stand_info = self.stand_assignments[drone_id]
            stand_name = stand_info.get("name", "未知机位")
            QMessageBox.warning(
                self, 
                "无法移除", 
                f"无人机 {drone_id} 当前正停在【{stand_name}】！\n请先在卡片下方点击「释放机位」，然后再执行移除。"
            )
            return

        try:
            # 自定义美化的确认弹窗
            msg = QMessageBox(self)
            msg.setWindowTitle("确认移除")
            msg.setText(f"确定要移除无人机 {drone_id} 吗？")
            msg.setIcon(QMessageBox.Question)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)

            # 美化 Yes / No 按钮（与其他弹窗风格统一）
            yes_btn = msg.button(QMessageBox.Yes)
            no_btn = msg.button(QMessageBox.No)
            if yes_btn:
                yes_btn.setText("确定")
                yes_btn.setStyleSheet(
                    """
                    QPushButton {
                        background-color: #409EFF;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #66b1ff; }
                    QPushButton:pressed { background-color: #3a8ee6; }
                    """
                )
            if no_btn:
                no_btn.setText("取消")
                no_btn.setStyleSheet(
                    """
                    QPushButton {
                        background-color: #909399;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #a6a9ad; }
                    QPushButton:pressed { background-color: #848688; }
                    """
                )

            reply = msg.exec_()
        except Exception as e:
            # 即便连弹窗都失败，也不要让应用直接崩
            return

        if reply != QMessageBox.Yes:
            self.info_display.append(f"ℹ️ 已取消移除无人机 {drone_id}")
            return

        # 1. 兜底逻辑：如果已分配机位，先释放机位（虽然上面已经拦截了，但保留作为底层兜底）
        try:
            if drone_id in self.stand_assignments:
                stand_info = self.stand_assignments[drone_id]
                self.release_stand(drone_id)
                self.info_display.append(
                    f"🔄 无人机 {drone_id} 的机位 {stand_info['name']} 已自动释放"
                )
        except Exception as e:
            pass

        # 2. 查找对应的工作线程
        worker_to_stop = None
        try:
            for worker in list(self.drone_workers):
                if getattr(worker, "drone_id", None) == str(drone_id):
                    worker_to_stop = worker
                    break

            if worker_to_stop:
                # 先从列表中移除，防止其他地方继续访问
                try:
                    if worker_to_stop in self.drone_workers:
                        self.drone_workers.remove(worker_to_stop)
                except Exception as e:
                    pass

                try:
                    worker_to_stop.stop()
                except Exception as e:
                    pass

                try:
                    worker_to_stop.finished.connect(worker_to_stop.deleteLater)
                except Exception as e:
                    pass
            else:
                pass
        except Exception as e:
            pass

        # 3. 定义 UI 和地图清理逻辑，使用 QTimer 延迟一点时间执行，避免和线程抢资源
        def _cleanup_ui_and_map():
            try:
                # 3.1 删除卡片
                try:
                    if drone_id in self.drone_cards:
                        # 使用堆叠容器移除卡片
                        self.card_stack.remove_card(drone_id)
                        del self.drone_cards[drone_id]
                except Exception as e:
                    pass

                # 3.2 同步移除飞手信息并刷新面板
                try:
                    if hasattr(self, "drone_pilots") and str(drone_id) in self.drone_pilots:
                        del self.drone_pilots[str(drone_id)]
                    # 从飞手堆叠容器中移除
                    if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                        self.pilot_stack.remove_row(str(drone_id))
                except Exception as e:
                    pass

                # 3.3 更新动态无人机列表
                try:
                    self.dynamic_drones = [
                        d for d in self.dynamic_drones if str(d.get("id")) != str(drone_id)
                    ]
                except Exception as e:
                    pass

                # 3.4 清理地图标记/轨迹/连线/标签（兼容没有这些对象的情况）
                try:
                    js_code = f"""
                    if (typeof droneMarkers !== 'undefined' && droneMarkers["{drone_id}"]) {{ droneMarkers["{drone_id}"].setMap(null); delete droneMarkers["{drone_id}"]; }}
                    if (typeof droneTrails !== 'undefined' && droneTrails["{drone_id}"]) {{ droneTrails["{drone_id}"].setMap(null); delete droneTrails["{drone_id}"]; }}
                    if (typeof linkLines !== 'undefined' && linkLines["{drone_id}"]) {{ linkLines["{drone_id}"].setMap(null); delete linkLines["{drone_id}"]; }}
                    if (typeof linkLabelsDrone !== 'undefined' && linkLabelsDrone["{drone_id}"]) {{ linkLabelsDrone["{drone_id}"].setMap(null); delete linkLabelsDrone["{drone_id}"]; }}
                    if (typeof linkLabelsGS !== 'undefined' && linkLabelsGS["{drone_id}"]) {{ linkLabelsGS["{drone_id}"].setMap(null); delete linkLabelsGS["{drone_id}"]; }}
                    if (typeof droneTrailPaths !== 'undefined' && droneTrailPaths["{drone_id}"]) {{ delete droneTrailPaths["{drone_id}"]; }}
                    if (typeof dronePosMap !== 'undefined' && dronePosMap["{drone_id}"]) {{ delete dronePosMap["{drone_id}"]; }}
                    """
                    self.browser.page().runJavaScript(js_code)
                except Exception as e:
                    pass

                self.info_display.append(f"❌ 已移除无人机 ID: {drone_id}")
            except Exception as e:
                pass

        try:
            # 给线程更多时间停止，避免资源抢占和崩溃
            delay = 500 if worker_to_stop else 100
            QTimer.singleShot(delay, _cleanup_ui_and_map)
        except Exception as e:
            _cleanup_ui_and_map()

    def show_add_drone_dialog(self):
        from ui.dialogs import AddDroneDialog
        from PyQt5.QtWidgets import QMessageBox
        dialog = AddDroneDialog(list(self.drone_cards.keys()), self)
        result = dialog.exec_()

        if result == dialog.Accepted:
            drone_config = dialog.get_drone_config()
            new_drone_id = str(drone_config["id"])
            
            if new_drone_id in self.drone_cards:
                QMessageBox.warning(self, "警告", f"ID {new_drone_id} 已存在，请使用其他ID")
                return

            new_drone_name = drone_config.get("name", "").strip()
            if not new_drone_name:
                new_drone_name = f"无人机 {new_drone_id}" 
                
            for existing_id, card in self.drone_cards.items():
                existing_name = getattr(card, "drone_name", f"无人机 {existing_id}")
                if new_drone_name == existing_name:
                    QMessageBox.warning(self, "名称冲突", f"无人机名称【{new_drone_name}】已被使用！\n请重新添加并输入一个不同的名称以作区分。")
                    return
            
            pilot = drone_config.get("pilot", {})
            p_name = pilot.get("name", "").strip()
            p_email = pilot.get("email", "").strip()
            p_phone = pilot.get("phone", "").strip()
            
            for other_id, info in self.drone_pilots.items():
                if p_name and p_name == info.get("name", ""):
                    QMessageBox.warning(self, "警告", f"飞手姓名【{p_name}】已被使用，请重新添加并更换姓名！")
                    return
                if p_email and p_email == info.get("email", ""):
                    QMessageBox.warning(self, "警告", f"飞手邮箱【{p_email}】已被使用，请重新添加并更换邮箱！")
                    return
                if p_phone and p_phone == info.get("phone", ""):
                    QMessageBox.warning(self, "警告", f"飞手电话【{p_phone}】已被使用，请重新添加并更换电话！")
                    return

            self.dynamic_drones.append(drone_config)
            self.add_drone_card(drone_config)

            if drone_config.get("auto_connect", False):
                QTimer.singleShot(500, lambda: self.on_drone_connect_clicked(drone_config["id"], True))
                
    def on_drone_connect_clicked(self, drone_id: str, connect: bool):
        for worker in self.drone_workers:
            if worker.drone_id == drone_id:
                if connect:
                    worker.connect_drone()
                    self.info_display.append(f"🔄 正在连接无人机 {drone_id}...")
                else:
                    worker.disconnect_drone()
                    self.info_display.append(f"🔄 正在断开无人机 {drone_id}...")
                break

    def on_drone_connection_changed(self, drone_id: str, connected: bool):
        if drone_id in self.drone_cards:
            self.drone_cards[drone_id].set_connected(connected)
            if not connected:
                self.radar_targets.pop(drone_id, None)
                self._refresh_radar_targets()
                try: self.drone_cards[drone_id].clear_data()
                except Exception:
                    try: self.drone_cards[drone_id].update_data(None, None, None, None, None)
                    except Exception: pass

                js_code = f"""
                if (typeof clearDroneMulti === 'function') {{
                    clearDroneMulti("{drone_id}");
                }} else {{
                    if (typeof droneMarkers !== 'undefined' && droneMarkers["{drone_id}"]) {{ droneMarkers["{drone_id}"].setMap(null); delete droneMarkers["{drone_id}"]; }}
                    if (typeof droneTrails !== 'undefined' && droneTrails["{drone_id}"]) {{ droneTrails["{drone_id}"].setMap(null); delete droneTrails["{drone_id}"]; }}
                    if (typeof linkLines !== 'undefined' && linkLines["{drone_id}"]) {{ linkLines["{drone_id}"].setMap(null); delete linkLines["{drone_id}"]; }}
                    if (typeof linkLabelsDrone !== 'undefined' && linkLabelsDrone["{drone_id}"]) {{ linkLabelsDrone["{drone_id}"].setMap(null); delete linkLabelsDrone["{drone_id}"]; }}
                    if (typeof linkLabelsGS !== 'undefined' && linkLabelsGS["{drone_id}"]) {{ linkLabelsGS["{drone_id}"].setMap(null); delete linkLabelsGS["{drone_id}"]; }}
                    if (typeof droneTrailPaths !== 'undefined' && droneTrailPaths["{drone_id}"]) {{ delete droneTrailPaths["{drone_id}"]; }}
                    if (typeof dronePosMap !== 'undefined' && dronePosMap["{drone_id}"]) {{ delete dronePosMap["{drone_id}"]; }}
                }}
                """
                try: self.browser.page().runJavaScript(js_code)
                except Exception: pass

            status = "✅ 已连接" if connected else "❌ 已断开"
            self.info_display.append(f"无人机 {drone_id} {status}")

    def on_drone_status(self, text: str):
        self.info_display.append(text)

    def _refresh_radar_targets(self):
        if hasattr(self.info_display, "set_targets"):
            targets = list(self.radar_targets.values()) + list(self.adsb_targets.values())
            self.info_display.set_targets(targets)

    def refresh_adsb_targets(self):
        snapshot = get_aircraft_snapshot(max_age=ADSB_TARGET_MAX_AGE_SECONDS)
        targets = {}
        for icao, data in snapshot.items():
            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                continue

            label = (data.get("callsign") or "").strip() or icao
            targets[f"adsb:{icao}"] = {
                "lat": lat,
                "lon": lon,
                "name": label[:10],
            }

        self.adsb_targets = targets
        self._refresh_radar_targets()

    def _update_ground_station_panel(self, lat, lng, updated_at=None):
        if hasattr(self.info_display, "set_center"):
            self.info_display.set_center(lat, lng)
        if hasattr(self.weather_card, "update_station_info"):
            self.weather_card.update_station_info(lat, lng, updated_at)

    def on_drone_telemetry(self, telem: dict):
        drone_id = str(telem.get("id", "1"))
        drone_name = telem.get("name") or f"无人机 {drone_id}"
        lat_wgs84 = telem.get("lat")
        lng_wgs84 = telem.get("lng")
        alt = telem.get("alt")
        battery = telem.get("battery")
        sats = telem.get("sats")
        connected = telem.get("connected", False)

        if drone_id in self.drone_cards:
            self.drone_cards[drone_id].update_data(lat_wgs84, lng_wgs84, alt, battery, sats)
            self.drone_cards[drone_id].set_connected(connected)

        if connected and lat_wgs84 is not None and lng_wgs84 is not None:
            self.radar_targets[drone_id] = {
                "lat": lat_wgs84,
                "lon": lng_wgs84,
                "name": drone_name,
            }
            self._refresh_radar_targets()
        elif drone_id in self.radar_targets:
            self.radar_targets.pop(drone_id, None)
            self._refresh_radar_targets()

        if connected and lat_wgs84 is not None and lng_wgs84 is not None:
            lat_gcj, lng_gcj = wgs84_to_gcj02(lat_wgs84, lng_wgs84)
            alt_js = "null" if alt is None else float(alt)
            battery_js = "null" if battery is None else float(battery)
            sats_js = "null" if sats is None else float(sats)

            safe_url = "file:///" + DRONE_SVG_PATH.replace("\\", "/")
            icon_html = f"<img src='{safe_url}' style='width:36px; height:36px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5)); display:block;'>"

            js_code = f"""
            if (typeof updateDroneMulti === 'function') {{
                updateDroneMulti("{drone_id}", {lat_gcj}, {lng_gcj}, {alt_js}, 
                                {battery_js}, {sats_js}, 
                                {{name: "{drone_name}", emoji: "{icon_html}"}} );
            }}
            """
            self.browser.page().runJavaScript(js_code)

    def show_stand_assign_dialog(self, drone_id):
        if isinstance(drone_id, str) and drone_id.startswith("release:"):
            self.release_stand(drone_id.replace("release:", ""))
            return

        if not self.last_weather_data:
            QMessageBox.warning(self, "警告", "暂无天气数据，无法进行分配")
            return

        drone_card = self.drone_cards.get(drone_id)
        if not drone_card: return

        current_assignments = {d_id: info["id"] for d_id, info in self.stand_assignments.items()}

        dialog = StandAssignDialog(
            drone_id=drone_id,
            drone_name=drone_card.drone_name,
            drone_model=drone_card.drone_model,
            weather_data=self.last_weather_data,
            current_assignments=current_assignments,
            parent=self
        )
        dialog.standAssigned.connect(self.on_stand_assigned)
        dialog.exec_()

    def on_stand_assigned(self, drone_id, stand_info):
        if drone_id in self.stand_assignments:
            self.release_stand(drone_id)
        self.assign_stand(drone_id, stand_info)

    def smart_assign_all_drones(self):
        if not self.last_weather_data:
            QMessageBox.warning(self, "警告", "暂无天气数据，无法进行智能分配")
            return

        from utils.weather_analyzer import WeatherAnalyzer
        from utils.stand_store import list_stands
        analyzer = WeatherAnalyzer()
        all_stands = list_stands()
        occupied_stands = list(self.occupied_stands)
        assigned_count = 0

        for drone_id, card in self.drone_cards.items():
            if drone_id in self.stand_assignments: continue
            best_stand = analyzer.get_best_stand_for_drone(
                drone_model=card.drone_model,
                weather_data=self.last_weather_data,
                occupied_stands=occupied_stands,
                stands=all_stands,
            )
            if best_stand:
                import time
                best_stand["assigned_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                best_stand["drone_id"] = drone_id
                self.assign_stand(drone_id, best_stand)
                occupied_stands.append(best_stand["id"])
                assigned_count += 1

        if assigned_count > 0:
            self.info_display.append(f"✅ 智能分配完成，已分配 {assigned_count} 架无人机")
        else:
            self.info_display.append("⚠️ 没有可分配的无人机或机位已满")

    def assign_stand(self, drone_id, stand_info):
        self.stand_assignments[drone_id] = stand_info
        self.occupied_stands.add(stand_info["id"])
        if drone_id in self.drone_cards:
            self.drone_cards[drone_id].set_assigned_stand(stand_info["id"], stand_info)
        
        if hasattr(self, 'stand_stack'):
            self.stand_stack.update_assignments(self.stand_assignments)
            try:
                stand_id = stand_info["id"]
                if hasattr(self.stand_stack, "show_card"):
                    self.stand_stack.show_card(stand_id)
            except Exception: pass
                
        self.info_display.append(f"✅ 无人机 {drone_id} 已分配到机位 {stand_info['name']}")
        try: self._maybe_send_assign_email(drone_id, stand_info)
        except Exception as e: self.info_display.append(f"✉️ 邮件通知失败: {e}")

    def release_stand(self, drone_id):
        if drone_id in self.stand_assignments:
            stand_info = self.stand_assignments[drone_id]
            stand_id = stand_info["id"]
            stand_name = stand_info["name"]

            self.occupied_stands.discard(stand_id)
            del self.stand_assignments[drone_id]

            if drone_id in self.drone_cards:
                self.drone_cards[drone_id].set_assigned_stand(None, None)
                self.drone_cards[drone_id].update()

            if hasattr(self, 'stand_stack'):
                self.stand_stack.update_assignments(self.stand_assignments)

            self.info_display.append(f"✅ 无人机 {drone_id} 的机位 {stand_name} 已释放")
            return True
        return False

    def on_stand_released(self, stand_id):
        for drone_id, stand_info in list(self.stand_assignments.items()):
            if stand_info["id"] == stand_id:
                self.release_stand(drone_id)
                break

    def _get_best_position(self):
        """获取最优的地面站位置，按优先级依次尝试：
        0. 树莓派 GPS（串口 NMEA）
        1. Windows GPS
        2. RID 设备心跳 GPS
        3. 任一在线无人机的遥测位置
        4. 返回 (None, None)
        """
        # 0. 树莓派 GPS（优先，适合无人值守运行）
        lat, lng = get_pi_gps_sync()
        if lat is not None and lng is not None:
            return (lat, lng, "树莓派GPS")

        # 1. Windows GPS
        lat, lng = get_location_sync()
        if lat is not None and lng is not None:
            return (lat, lng, "Windows GPS")

        # 2. RID 设备心跳 GPS
        try:
            if hasattr(self, 'rid_card') and self.rid_card:
                rid_lat, rid_lng = self.rid_card.get_heartbeat_position()
                if rid_lat is not None and rid_lng is not None:
                    return (rid_lat, rid_lng, "RID设备GPS")
        except Exception:
            pass

        # 3. 任一在线无人机的遥测位置
        try:
            for target in self.radar_targets.values():
                t_lat = target.get("lat")
                t_lon = target.get("lon")
                if t_lat is not None and t_lon is not None:
                    return (t_lat, t_lon, "无人机遥测")
        except Exception:
            pass

        return (None, None, None)

    def get_location_and_update_map(self):
        """后台定位：WinRT / 串口定位可能卡数秒，放线程里跑，UI 不阻塞。"""
        if getattr(self, "_locate_worker", None) and self._locate_worker.isRunning():
            return
        worker = _LocateWorker(self)
        worker.done.connect(self._on_located)
        self._locate_worker = worker
        worker.start()

    def _on_located(self, lat_wgs84, lng_wgs84, source):
        # 后台只查 GPS；RID 心跳 / 遥测兜底仍在主线程做
        if lat_wgs84 is None or lng_wgs84 is None:
            try:
                if hasattr(self, "rid_card") and self.rid_card:
                    rid_lat, rid_lng = self.rid_card.get_heartbeat_position()
                    if rid_lat is not None and rid_lng is not None:
                        lat_wgs84, lng_wgs84, source = rid_lat, rid_lng, "RID设备GPS"
            except Exception:
                pass
        if lat_wgs84 is None or lng_wgs84 is None:
            try:
                for target in self.radar_targets.values():
                    t_lat, t_lon = target.get("lat"), target.get("lon")
                    if t_lat is not None and t_lon is not None:
                        lat_wgs84, lng_wgs84, source = t_lat, t_lon, "无人机遥测"
                        break
            except Exception:
                pass

        if lat_wgs84 is not None and lng_wgs84 is not None:
            source_info = f" (来源: {source})" if source else ""
            self.info_display.append(f"📍 地面站经纬度{source_info}: \n        纬度={lat_wgs84:.6f}\n        经度={lng_wgs84:.6f}\n")
            self.current_location = (lat_wgs84, lng_wgs84)
            self._update_ground_station_panel(lat_wgs84, lng_wgs84)
            self.update_weather()
            self.weather_timer.start(WEATHER_UPDATE_INTERVAL * 1000)
        else:
            self.info_display.append("⚠️ 无法获取位置，使用默认位置")
            self.current_location = DEFAULT_MAP_CENTER
            self._update_ground_station_panel(*DEFAULT_MAP_CENTER)
            self.update_weather()
            lat_wgs84, lng_wgs84 = DEFAULT_MAP_CENTER

        # 无论是否获取到真实位置，都更新地图上的地面站标记
        # 这样"返回地面站"按钮始终可用
        lat_gcj, lng_gcj = wgs84_to_gcj02(lat_wgs84, lng_wgs84)

        marker_icon, panel_icon = "🏠", "🏠"
        try:
            if os.path.exists(GROUND_STATION_SVG_PATH):
                with open(GROUND_STATION_SVG_PATH, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(GROUND_STATION_SVG_PATH)[1].lower()
                mime_type = "image/svg+xml" if ext == ".svg" else f"image/{ext.strip('.')}"
                safe_url = f"data:{mime_type};base64,{b64_data}"
                marker_icon = f"<img src='{safe_url}' style='width:36px; height:36px; filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5)); display:block;'>"
                panel_icon = f"<img src='{safe_url}' style='width:20px; height:20px; display:block;'>"
        except Exception: pass

        js_code = f"""
        if (typeof updateGroundStation === 'function') {{
            updateGroundStation({lat_gcj}, {lng_gcj}, {{ markerIcon: "{marker_icon}", panelIcon: "{panel_icon}" }});
        }}
        """
        self.browser.page().runJavaScript(js_code)

    def update_weather(self):
        if not self.current_location:
            return
        # 后台线程拉取：主线程只投递请求，界面不再被网络请求卡住
        if not getattr(self, "_weather_worker", None):
            self._weather_worker = _WeatherWorker(self.weather_manager, self)
            self._weather_worker.ready.connect(self._on_weather_ready)
            self._weather_worker.start()
        self._weather_worker.request(*self.current_location)

    def _on_weather_ready(self, weather_data):
        if not isinstance(weather_data, dict) or not weather_data:
            return
        self.last_weather_data = weather_data
        updated_at = weather_data.get("last_updated")
        try:
            if self.current_location:
                self._update_ground_station_panel(self.current_location[0], self.current_location[1], updated_at)
            self.weather_card.update_weather(weather_data)
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            if getattr(self, "_weather_worker", None):
                self._weather_worker.stop()
                self._weather_worker.wait(1500)
        except Exception:
            pass
        self.weather_timer.stop()
        try:
            self.adsb_timer.stop()
        except Exception:
            pass
        try:
            self._pos_refresh_timer.stop()
        except Exception:
            pass
        try:
            self._rid_sync_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, '_adsb_watchdog_timer'):
                self._adsb_watchdog_timer.stop()
        except Exception:
            pass
        try:
            self._disconnect_adsb()
        except Exception:
            pass
        try:
            if hasattr(self, 'sensor_card') and self.sensor_card:
                self.sensor_card.stop_and_cleanup()
        except Exception:
            pass
        try:
            if hasattr(self, 'rid_card') and self.rid_card:
                self.rid_card.stop_and_cleanup()
        except Exception:
            pass
        try:
            if self._asyncio_loop is not None and not self._asyncio_loop.is_closed():
                asyncio.set_event_loop(self._asyncio_loop)
                self._asyncio_loop.run_until_complete(self.weather_manager.stop_auto_update())
                self._asyncio_loop.close()
        except: pass
        for worker in self.drone_workers:
            try: worker.stop(); worker.wait(1500)
            except: pass
        super().closeEvent(event)

    def show_pilot_info_dialog(self, drone_id: str):
        info = self.drone_pilots.get(str(drone_id), {}) if hasattr(self, "drone_pilots") else {}
        name = info.get("name") or ""
        email = info.get("email") or ""
        phone = info.get("phone") or ""
        dlg = PilotInfoDialog(name, email, phone, parent=self)
        dlg.current_drone_id = str(drone_id) 
        
        if dlg.exec_() == dlg.Accepted:
            values = dlg.get_values()
            self.drone_pilots[str(drone_id)] = {
                "name": values.get("name", ""),
                "email": values.get("email", ""),
                "phone": values.get("phone", ""),
            }
            self.info_display.append(f"👨‍✈️ 已更新无人机 {drone_id} 的飞手信息")
            try:
                if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                    drone_name = self.drone_cards.get(str(drone_id)).drone_name if str(drone_id) in self.drone_cards else f"无人机 {drone_id}"
                    self.pilot_stack.upsert_row(
                        drone_id=str(drone_id),
                        drone_name=drone_name,
                        pilot=self.drone_pilots.get(str(drone_id), {})
                    )
            except Exception: pass
                
    def on_pilot_updated_from_panel(self, drone_id: str, data: dict):
        import re
        from PyQt5.QtWidgets import QMessageBox

        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        phone = (data.get("phone") or "").strip()

        if email and not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
            QMessageBox.warning(self, "格式错误", f"无人机 {drone_id} 的邮箱格式不规范！\n请检查后重新输入。")
            self._refresh_pilot_panel()
            return
        if phone and not re.match(r'^1[3-9]\d{9}$', phone):
            QMessageBox.warning(self, "格式错误", f"无人机 {drone_id} 的手机号格式不规范！\n请输入有效的11位手机号码。")
            self._refresh_pilot_panel()
            return

        for other_id, info in self.drone_pilots.items():
            if str(other_id) == str(drone_id): continue
            
            other_pilot_name = info.get("name", "")
            other_email = info.get("email", "")
            other_phone = info.get("phone", "")
            
            other_drone_name = f"无人机 {other_id}"
            if hasattr(self, "drone_cards") and str(other_id) in self.drone_cards:
                other_drone_name = self.drone_cards[str(other_id)].drone_name

            if name and name == other_pilot_name:
                QMessageBox.warning(self, "信息冲突", f"该姓名已被【{other_drone_name}】的飞手使用！\n请使用其他姓名以作区分。")
                self._refresh_pilot_panel()
                return
            if email and email == other_email:
                QMessageBox.warning(self, "信息冲突", f"该邮箱已被【{other_drone_name}】使用！\n请更换其他邮箱。")
                self._refresh_pilot_panel()
                return
            if phone and phone == other_phone:
                QMessageBox.warning(self, "信息冲突", f"该手机号已被【{other_drone_name}】使用！\n请更换其他手机号。")
                self._refresh_pilot_panel()
                return

        self.drone_pilots[str(drone_id)] = {"name": name, "email": email, "phone": phone}
        self.info_display.append(f"👨‍✈️ 飞手面板已成功更新无人机 {drone_id} 的飞手信息")
        
    def _on_pilot_view_requested(self, drone_id: str):
        if self.focusWidget(): self.focusWidget().clearFocus()

        def open_dialog():
            info = self.drone_pilots.get(str(drone_id), {}) if hasattr(self, "drone_pilots") else {}
            name = info.get("name") or ""
            email = info.get("email") or ""
            phone = info.get("phone") or ""
            
            from ui.dialogs import PilotInfoDialog
            dlg = PilotInfoDialog(name, email, phone, parent=self)
            dlg.current_drone_id = str(drone_id) 
            
            if dlg.exec_() == dlg.Accepted:
                values = dlg.get_values()
                self.drone_pilots[str(drone_id)] = {
                    "name": values.get("name", ""),
                    "email": values.get("email", ""),
                    "phone": values.get("phone", ""),
                }
                try:
                    if hasattr(self, "pilot_stack") and self.pilot_stack is not None:
                        drone_name = self.drone_cards.get(str(drone_id)).drone_name if str(drone_id) in self.drone_cards else f"无人机 {drone_id}"
                        self.pilot_stack.upsert_row(drone_id=str(drone_id), drone_name=drone_name, pilot=self.drone_pilots.get(str(drone_id), {}))
                except Exception: pass
                self.info_display.append(f"👨‍✈️ 通过飞手面板查看并更新了无人机 {drone_id} 的飞手信息")

        QTimer.singleShot(50, open_dialog)

    def _maybe_send_assign_email(self, drone_id: str, stand_info: dict):
        if not SMTP_ENABLED or not self.mailer: return
        pilot = self.drone_pilots.get(str(drone_id), {}) if hasattr(self, "drone_pilots") else {}
        to_email = (pilot.get("email") or "").strip()
        if not to_email:
            self.info_display.append("✉️ 跳过邮件：未设置飞手邮箱")
            return

        drone_name = self.drone_cards.get(str(drone_id)).drone_name if str(drone_id) in self.drone_cards else f"无人机 {drone_id}"
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
        self.mailer.send_email(
            sender=MAIL_SENDER or SMTP_USERNAME,
            to=[to_email],
            subject=subject,
            body=body,
            body_is_html=True,
        )
        self.info_display.append(f"✉️ 已发送机位分配通知至 {to_email}")

    def _collect_current_drones(self):
        drones = []
        try:
            for did, card in (self.drone_cards or {}).items():
                drones.append({"id": did, "name": getattr(card, "drone_name", f"无人机 {did}")})
        except Exception: pass
        return drones

    def _refresh_pilot_panel(self):
        if hasattr(self, "pilot_panel") and self.pilot_panel is not None:
            drones = self._collect_current_drones()
            self.pilot_panel.set_data(drones, self.drone_pilots or {})
