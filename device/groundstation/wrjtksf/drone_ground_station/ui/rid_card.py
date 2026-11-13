# ui/rid_card.py
"""RID900 无人机探测模块 — PyQt5 集成卡片
实时显示 RID900 探测到的无人机信息，通过串口接收 $HBRID / $GBRID 报文。

界面布局：
  - 顶部：心跳信息栏（设备ID / RSSI / SNR / GPS / 报文计数）
  - 中部：无人机简略列表（序列号 / 型号 / RSSI / 速度），点击弹出详情窗口
"""

import sys
import os
import time
import threading
import queue
from typing import Optional, Dict, List
from collections import deque

from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QSizePolicy, QMessageBox, QDialog,
                             QGridLayout, QGroupBox, QScrollArea, QApplication)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QColor, QBrush, QFont

# ── 导入 RID 解析模块 ──
_rid_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "rid")
_rid_path = os.path.normpath(_rid_path)
if _rid_path not in sys.path:
    sys.path.insert(0, _rid_path)

try:
    from rid_module import RIDParser, RIDSerialReader, DroneTracker, HeartbeatInfo, DroneInfo
except ImportError:
    RIDParser = None
    RIDSerialReader = None
    DroneTracker = None
    HeartbeatInfo = None
    DroneInfo = None

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None


DEFAULT_BAUDRATE = 115200
STALE_TIMEOUT = 60.0
GUI_REFRESH_MS = 200


# ======================================================
#  后台读取线程
# ======================================================

class RIDReaderThread(QThread):
    """后台线程：持续从 RID900 串口读取报文并解析"""
    dataReady = pyqtSignal(str, object)      # (msg_type, data)
    statusChanged = pyqtSignal(str, object)   # (status, info)

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self._running = False
        self._ser = None
        self._buffer = b""
        self._error_count = 0

    def run(self):
        self._running = True
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=0.02,
                rtscts=False,          # 禁用硬件流控 (Linux 兼容性关键)
                dsrdtr=False)          # 禁用 DSR/DTR 流控
            # 关键：Linux 下模拟 stty -hupcl 效果，拉低 DTR 唤醒 RID 传感器
            self._ser.setDTR(False)
            time.sleep(0.5)   # 等待传感器稳定
            self.statusChanged.emit("connected", (self.port, self.baudrate))
        except Exception as e:
            self.statusChanged.emit("error", str(e))
            return

        while self._running and self._ser and self._ser.is_open:
            try:
                chunk = self._ser.read(1024)
                if chunk:
                    self._buffer += chunk
                    self._process_buffer()
            except serial.SerialException as e:
                self.statusChanged.emit("disconnected", str(e))
                break
            except Exception as e:
                self._error_count += 1
                if self._error_count > 100:
                    self.statusChanged.emit("error", f"连续读取错误: {e}")
                    break

        self._close()

    def _process_buffer(self):
        while True:
            idx = self._buffer.find(b"\n")
            if idx == -1:
                break
            line_bytes = self._buffer[:idx]
            self._buffer = self._buffer[idx + 1:]
            try:
                line = line_bytes.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not line:
                continue
            if RIDParser:
                msg_type, data = RIDParser.parse_line(line)
                if msg_type:
                    self.dataReady.emit(msg_type, data)

    def _close(self):
        self._running = False
        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        self._close()
        self.wait(2000)


# ======================================================
#  无人机详情弹窗
# ======================================================

class DroneDetailDialog(QDialog):
    """点击无人机后弹出的详情窗口"""

    def __init__(self, drone: DroneInfo, parent=None):
        super().__init__(parent)
        self.drone = drone
        self.setWindowTitle(f"无人机详情 — {drone.drone_serial_num}")
        self.setMinimumSize(520, 520)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f0f9ff, stop:1 #e6f7ff);
            }
            QGroupBox {
                border: 2px solid #69c0ff;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: #003a8c;
                background-color: rgba(255,255,255,0.7);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        d = self.drone
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(10)

        # ── 标题 ──
        title = QLabel(f"🛰 无人机 [{d.drone_serial_num}] 完整信息")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #003a8c; background: transparent;")
        main_layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_widget = QFrame()
        scroll_widget.setStyleSheet("QFrame { background: transparent; }")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)

        # ── 信号质量 ──
        sig_group = self._add_group("📶 信号质量", scroll_layout)
        sig_grid = QGridLayout(sig_group)
        sig_grid.setSpacing(8)
        self._add_field(sig_grid, 0, 0, "RSSI", f"{d.detect_rssi} dBm", self._rssi_color(d.detect_rssi))
        self._add_field(sig_grid, 0, 1, "SNR", f"{d.detect_snr} dB", "#1890ff")

        # ── 身份信息 ──
        id_group = self._add_group("🆔 身份信息", scroll_layout)
        id_grid = QGridLayout(id_group)
        id_grid.setSpacing(8)
        self._add_field(id_grid, 0, 0, "序列号", d.drone_serial_num, "#1890ff")
        self._add_field(id_grid, 0, 1, "厂商", d.vendor_str, "#1890ff")
        self._add_field(id_grid, 1, 0, "型号", d.product_type_str, "#1890ff")
        self._add_field(id_grid, 1, 1, "设备类型", str(d.drone_type), "#1890ff")

        # ── 位置信息 ──
        pos_group = self._add_group("📍 位置信息", scroll_layout)
        pos_grid = QGridLayout(pos_group)
        pos_grid.setSpacing(8)
        self._add_field(pos_grid, 0, 0, "经度", f"{d.drone_longitude:.6f}" if d.drone_longitude else "--", "#1890ff")
        self._add_field(pos_grid, 0, 1, "纬度", f"{d.drone_latitude:.6f}" if d.drone_latitude else "--", "#1890ff")
        self._add_field(pos_grid, 1, 0, "离地高度", f"{d.height:.1f} m" if d.height else "-- m", "#1890ff")
        self._add_field(pos_grid, 1, 1, "海拔高度", f"{d.altitude:.1f} m" if d.altitude else "-- m", "#1890ff")
        self._add_field(pos_grid, 2, 0, "气压高度", f"{d.pressure:.1f} m" if d.pressure else "-- m", "#1890ff")

        # ── 飞行数据 ──
        fly_group = self._add_group("🧭 飞行数据", scroll_layout)
        fly_grid = QGridLayout(fly_group)
        fly_grid.setSpacing(8)
        self._add_field(fly_grid, 0, 0, "航向角", f"{d.yaw_angle}° {d.heading_str}", "#1890ff")
        self._add_field(fly_grid, 0, 1, "水平速度", f"{d.speed_kmh:.1f} km/h", "#1890ff")
        self._add_field(fly_grid, 1, 0, "垂直速度", f"{d.up_speed} m/s", "#1890ff")
        self._add_field(fly_grid, 1, 1, "设备种类", str(d.drone_class), "#1890ff")

        # ── 精度信息 ──
        acc_group = self._add_group("🎯 精度信息", scroll_layout)
        acc_grid = QGridLayout(acc_group)
        acc_grid.setSpacing(8)
        self._add_field(acc_grid, 0, 0, "位置误差", f"{d.position_error} m" if d.position_error else "-- m", "#1890ff")
        self._add_field(acc_grid, 0, 1, "高度误差", f"{d.height_error} m" if d.height_error else "-- m", "#1890ff")
        self._add_field(acc_grid, 1, 0, "状态信息", str(d.state_info), "#1890ff")

        # ── 飞手位置 ──
        if d.has_pilot_position:
            pilot_group = self._add_group("🎮 飞手位置", scroll_layout)
            pilot_grid = QGridLayout(pilot_group)
            pilot_grid.setSpacing(8)
            self._add_field(pilot_grid, 0, 0, "飞手经度", f"{d.pilot_longitude:.6f}", "#bc8cff")
            self._add_field(pilot_grid, 0, 1, "飞手纬度", f"{d.pilot_latitude:.6f}", "#bc8cff")
            self._add_field(pilot_grid, 1, 0, "飞手海拔", f"{d.pilot_height:.1f} m" if d.pilot_height else "-- m", "#bc8cff")

        # ── 原始报文 ──
        raw_group = self._add_group("📝 原始报文", scroll_layout)
        raw_layout = QVBoxLayout(raw_group)
        raw_text = QLabel(d.raw if d.raw else "--")
        raw_text.setWordWrap(True)
        raw_text.setStyleSheet(
            "font-size: 10px; color: #595959; background: rgba(255,255,255,0.7); "
            "padding: 6px 8px; border-radius: 4px; border: 1px solid #dcdfe6;"
            "font-family: 'Consolas', 'Courier New', monospace;"
        )
        raw_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        raw_layout.addWidget(raw_text)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)

        # ── 关闭按钮 ──
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton { background-color: #409EFF; color: white; border: none; "
            "border-radius: 6px; padding: 8px 24px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #66b1ff; }")
        close_btn.clicked.connect(self.accept)
        main_layout.addWidget(close_btn, alignment=Qt.AlignCenter)

    def _add_group(self, title: str, parent_layout) -> QGroupBox:
        group = QGroupBox(title)
        parent_layout.addWidget(group)
        return group

    def _add_field(self, grid: QGridLayout, row: int, col: int,
                   label: str, value: str, value_color: str):
        lbl = QLabel(label + ":")
        lbl.setStyleSheet("font-size: 12px; color: #606266; font-weight: 600; background: transparent;")
        val = QLabel(value)
        val.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {value_color}; "
            "background: transparent; padding: 2px 0;"
        )
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(lbl, row, col * 2)
        grid.addWidget(val, row, col * 2 + 1)

    @staticmethod
    def _rssi_color(rssi: int) -> str:
        if rssi >= -50:
            return "#67C23A"
        elif rssi >= -70:
            return "#E6A23C"
        else:
            return "#F56C6C"


# ======================================================
#  RID 实时卡片（集成到地面站）
# ======================================================

class RIDRealtimeCard(QFrame):
    """RID900 无人机探测实时卡片
    平时显示心跳信息 + 简略无人机列表，点击无人机弹出详情窗口。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader: Optional[RIDReaderThread] = None
        self.tracker = DroneTracker(timeout=STALE_TIMEOUT) if DroneTracker else None
        self.heartbeat: Optional[HeartbeatInfo] = HeartbeatInfo() if HeartbeatInfo else None
        self.selected_serial: str = ""
        self._connected = False
        self._hbrid_count = 0
        self._gbird_count = 0
        self._update_count = 0
        self._detail_dialog: Optional[DroneDetailDialog] = None

        self.setup_ui()
        self._refresh_ports()

        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.timeout.connect(self._auto_refresh_ports)
        self._port_refresh_timer.start(2000)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start(GUI_REFRESH_MS)

        self._stale_timer = QTimer(self)
        self._stale_timer.timeout.connect(self._remove_stale)
        self._stale_timer.start(5000)

    def setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet("""
            RIDRealtimeCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f0f9ff, stop:1 #e6f7ff);
                border: 2px solid #69c0ff;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── 标题栏 + 连接控制 ──
        title_row = QHBoxLayout()
        title = QLabel("🛰 RID900 无人机探测")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #003a8c; background: transparent;")
        title_row.addWidget(title)

        title_row.addStretch()

        self.conn_indicator = QLabel("⚪")
        self.conn_indicator.setStyleSheet("font-size: 14px; background: transparent;")
        title_row.addWidget(self.conn_indicator)

        self.conn_status = QLabel("未连接")
        self.conn_status.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent; font-weight: 600;")
        title_row.addWidget(self.conn_status)
        layout.addLayout(title_row)

        # ── 串口选择行 ──
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        ctrl_row.addWidget(QLabel("串口:"))

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self.port_combo.setMaxVisibleItems(5)
        self.port_combo.setStyleSheet("""
            QComboBox {
                padding: 3px 8px; border: 1px solid #dcdfe6; border-radius: 4px;
                background: white; font-size: 12px; color: #303133;
            }
            QComboBox:hover { border-color: #409EFF; }
            QComboBox QAbstractItemView {
                min-width: 200px; outline: none; border: 1px solid #91d5ff;
                border-radius: 4px; background: white; padding: 4px; font-size: 12px;
                color: #303133; selection-background-color: #ecf5ff;
                selection-color: #1890ff;
            }
            QComboBox QAbstractItemView::item {
                padding: 5px 10px; min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #f0f9ff; color: #0050b3;
            }
        """)
        ctrl_row.addWidget(self.port_combo)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(32)
        refresh_btn.setStyleSheet(
            "QPushButton { border: 1px solid #dcdfe6; border-radius: 4px; background: white; }"
            "QPushButton:hover { background: #ecf5ff; }")
        refresh_btn.clicked.connect(self._refresh_ports)
        ctrl_row.addWidget(refresh_btn)

        ctrl_row.addStretch()

        self.connect_btn = QPushButton("⚡ 连接")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #67C23A; color: white; border: none; "
            "border-radius: 4px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #85ce61; }")
        self.connect_btn.clicked.connect(self._toggle_connection)
        ctrl_row.addWidget(self.connect_btn)

        layout.addLayout(ctrl_row)

        # ── 心跳信息栏（紧凑三行） ──
        hb_frame = QFrame()
        hb_frame.setStyleSheet(
            "QFrame { background-color: rgba(255,255,255,0.7); "
            "border: 1px solid #91d5ff; border-radius: 8px; }")
        hb_layout = QHBoxLayout(hb_frame)
        hb_layout.setContentsMargins(10, 6, 10, 6)
        hb_layout.setSpacing(12)

        self.hb_device = self._make_hb_item(hb_layout, "设备ID", "--")
        self.hb_rssi = self._make_hb_item(hb_layout, "RSSI", "-- dBm")
        self.hb_snr = self._make_hb_item(hb_layout, "SNR", "-- dB")
        self.hb_gps = self._make_hb_item(hb_layout, "GPS", "--, --")
        self.hb_alt = self._make_hb_item(hb_layout, "海拔", "-- m")
        self.hb_count = self._make_hb_item(hb_layout, "报文", "H:0 G:0")
        layout.addWidget(hb_frame)

        # ── 无人机列表（紧凑，点击弹窗） ──
        list_frame = QFrame()
        list_frame.setStyleSheet(
            "QFrame { background-color: rgba(255,255,255,0.7); "
            "border: 1px solid #91d5ff; border-radius: 8px; }")
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(6, 4, 6, 4)

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("  探测目标列表 (点击查看详情)"))
        list_header.addStretch()
        self.target_count_label = QLabel("在线目标: 0")
        self.target_count_label.setStyleSheet("font-size: 11px; color: #67C23A; font-weight: 600; background: transparent;")
        list_header.addWidget(self.target_count_label)
        list_layout.addLayout(list_header)

        self.drone_tree = QTreeWidget()
        self.drone_tree.setHeaderLabels(["序列号", "信号强度", "型号", "离地高(m)", "速度(km/h)", "航向"])
        self.drone_tree.setRootIsDecorated(False)
        self.drone_tree.setAlternatingRowColors(True)
        self.drone_tree.setStyleSheet("""
            QTreeWidget { border: 1px solid #dcdfe6; border-radius: 4px; font-size: 11px; }
            QTreeWidget::item { padding: 2px 4px; }
            QTreeWidget::item:selected { background-color: #ecf5ff; color: #303133; }
            QHeaderView::section {
                background-color: #f5f7fa; padding: 4px; border: none;
                border-bottom: 1px solid #ebeef5; font-weight: bold; font-size: 11px;
            }
        """)
        header = self.drone_tree.header()
        header.setStretchLastSection(True)
        for i in range(6):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.drone_tree.itemDoubleClicked.connect(self._on_drone_double_clicked)
        list_layout.addWidget(self.drone_tree)

        # 底部提示
        hint = QLabel("💡 双击目标行查看完整详情")
        hint.setStyleSheet("font-size: 10px; color: #8b949e; background: transparent; padding: 2px 4px;")
        list_layout.addWidget(hint)

        layout.addWidget(list_frame, 1)

    def _make_hb_item(self, parent_layout, label: str, default: str) -> QLabel:
        """创建心跳信息项"""
        wrap = QVBoxLayout()
        wrap.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 10px; color: #8b949e; background: transparent;")
        lbl.setAlignment(Qt.AlignCenter)
        wrap.addWidget(lbl)
        val = QLabel(default)
        val.setStyleSheet("font-size: 12px; font-weight: bold; color: #1890ff; background: transparent;")
        val.setAlignment(Qt.AlignCenter)
        wrap.addWidget(val)
        parent_layout.addLayout(wrap)
        return val

    # ── 串口刷新 ──
    def _refresh_ports(self):
        if serial is None:
            return
        current = self.port_combo.currentText()
        self.port_combo.clear()
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []
        self.port_combo.addItems(ports)
        if current and current in ports:
            self.port_combo.setCurrentText(current)
        elif ports:
            self.port_combo.setCurrentIndex(0)

    def _auto_refresh_ports(self):
        if self._connected:
            return
        if serial is None:
            return
        current = self.port_combo.currentText()
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return
        existing = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
        if set(ports) != set(existing):
            self.port_combo.clear()
            self.port_combo.addItems(ports)
            if current and current in ports:
                self.port_combo.setCurrentText(current)
            elif ports:
                self.port_combo.setCurrentIndex(0)

    # ── 连接/断开 ──
    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "串口未设置", "请先选择 RID900 串口！")
            return
        try:
            baud = int(DEFAULT_BAUDRATE)  # RID900 固定 115200
        except ValueError:
            baud = DEFAULT_BAUDRATE

        if self.tracker:
            self.tracker.clear()

        self.reader = RIDReaderThread(port, baud, parent=self)
        self.reader.dataReady.connect(self._on_rid_data)
        self.reader.statusChanged.connect(self._on_rid_status)
        self.reader.start()

        self._connected = True
        self.connect_btn.setText("⏹ 断开")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #F56C6C; color: white; border: none; "
            "border-radius: 4px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #f78989; }")
        self.port_combo.setEnabled(False)
        self.conn_indicator.setText("🟢")
        self.conn_status.setText("连接中...")
        self.conn_status.setStyleSheet(
            "font-size: 12px; color: #E6A23C; background: transparent; font-weight: 600;")

    def _disconnect(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        self._connected = False
        self.connect_btn.setText("⚡ 连接")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #67C23A; color: white; border: none; "
            "border-radius: 4px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #85ce61; }")
        self.port_combo.setEnabled(True)
        self.conn_indicator.setText("⚪")
        self.conn_status.setText("未连接")
        self.conn_status.setStyleSheet(
            "font-size: 12px; color: #8b949e; background: transparent; font-weight: 600;")
        self._clear_display()
        if self._detail_dialog:
            self._detail_dialog.close()
            self._detail_dialog = None

    # ── 数据回调 ──
    def _on_rid_data(self, msg_type: str, data):
        if msg_type == "HBRID":
            self._hbrid_count += 1
            self.heartbeat = data
        elif msg_type == "GBRID":
            self._gbird_count += 1
            if self.tracker:
                self.tracker.update(data)
        self._update_count += 1

    def _on_rid_status(self, status: str, info):
        if status == "connected":
            self._connected = True
            self.conn_indicator.setText("🟢")
            self.conn_status.setText(f"已连接 {info[0]} @{info[1]}")
            self.conn_status.setStyleSheet(
                "font-size: 12px; color: #67C23A; background: transparent; font-weight: 600;")
        elif status in ("error", "disconnected"):
            self.conn_indicator.setText("🔴")
            self.conn_status.setText(f"错误: {info}")
            self.conn_status.setStyleSheet(
                "font-size: 12px; color: #F56C6C; background: transparent; font-weight: 600;")
            if status == "disconnected":
                self._disconnect()

    def _refresh_display(self):
        """定时刷新 UI 显示 — 心跳 + 简略列表"""
        if self.heartbeat:
            hb = self.heartbeat
            self.hb_device.setText(hb.device_id if hb.device_id else "--")
            self.hb_rssi.setText(f"{hb.rssi} dBm" if hb.rssi else "-- dBm")
            self.hb_snr.setText(f"{hb.snr} dB" if hb.snr else "-- dB")
            if hb.longitude and hb.latitude:
                self.hb_gps.setText(f"{hb.latitude:.4f}, {hb.longitude:.4f}")
            else:
                self.hb_gps.setText("--, --")
            self.hb_alt.setText(f"{hb.altitude:.0f} m" if hb.altitude else "-- m")
        self.hb_count.setText(f"H:{self._hbrid_count} G:{self._gbird_count}")

        if self.tracker:
            drones = self.tracker.get_sorted(key='rssi', reverse=True)
            self.target_count_label.setText(f"在线目标: {len(drones)}")
            self._rebuild_tree(drones)

    def _rebuild_tree(self, drones: list):
        """重建 TreeWidget 列表（保持选中项）"""
        prev_selected = self.selected_serial
        self.drone_tree.clear()

        for d in drones:
            item = QTreeWidgetItem([
                d.drone_serial_num[:20] if d.drone_serial_num != "--" else "--",
                str(d.detect_rssi),
                d.product_type_str[:18] if d.product_type_str != "--" else "--",
                f"{d.height:.0f}" if d.height else "--",
                f"{d.speed_kmh:.1f}" if d.speed_kmh else "--",
                d.heading_str,
            ])
            item.setData(0, Qt.UserRole, d.drone_serial_num)
            # 信号强度着色
            rssi = d.detect_rssi
            if rssi >= -50:
                item.setForeground(1, QBrush(QColor("#67C23A")))
            elif rssi >= -70:
                item.setForeground(1, QBrush(QColor("#E6A23C")))
            else:
                item.setForeground(1, QBrush(QColor("#F56C6C")))
            self.drone_tree.addTopLevelItem(item)

            if d.drone_serial_num == prev_selected:
                self.drone_tree.setCurrentItem(item)

    def _on_drone_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击无人机列表项 → 弹出详情窗口"""
        serial_num = item.data(0, Qt.UserRole)
        self.selected_serial = serial_num
        if self.tracker:
            drone = self.tracker.get(serial_num)
            if drone:
                self._show_detail_dialog(drone)

    def _show_detail_dialog(self, drone: DroneInfo):
        """弹出无人机详情窗口"""
        if self._detail_dialog:
            self._detail_dialog.close()
        self._detail_dialog = DroneDetailDialog(drone, self)
        self._detail_dialog.show()

    def _remove_stale(self):
        if self.tracker:
            self.tracker.remove_stale()

    def _clear_display(self):
        self.drone_tree.clear()
        self.hb_device.setText("--")
        self.hb_rssi.setText("-- dBm")
        self.hb_snr.setText("-- dB")
        self.hb_gps.setText("--, --")
        self.hb_alt.setText("-- m")
        self.hb_count.setText("H:0 G:0")
        self.target_count_label.setText("在线目标: 0")
        self._hbrid_count = 0
        self._gbird_count = 0

    def stop_and_cleanup(self):
        """外部调用的安全停止方法"""
        self._port_refresh_timer.stop()
        self._refresh_timer.stop()
        self._stale_timer.stop()
        if self._connected:
            self._disconnect()

    def get_heartbeat_position(self):
        """获取 RID 设备自身的 GPS 位置 (纬度, 经度)，无数据返回 (None, None)。"""
        if self.heartbeat and self.heartbeat.latitude and self.heartbeat.longitude:
            try:
                return (float(self.heartbeat.latitude), float(self.heartbeat.longitude))
            except (ValueError, TypeError):
                return (None, None)
        return (None, None)
