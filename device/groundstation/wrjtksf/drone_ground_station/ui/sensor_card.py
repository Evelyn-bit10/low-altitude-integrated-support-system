# ui/sensor_card.py
"""三485传感器实时数据卡片（Modbus-RTU 单串口集线器版）
集成到地面站主界面中，以 PyQt5 卡片形式展示。
百叶箱传感器仅显示前3项：温度、湿度、气压。
"""

import struct
import time
import queue
from datetime import datetime
from typing import Optional, Dict

from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QGridLayout, QSizePolicy,
                             QMessageBox, QCheckBox, QSpinBox, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None


# ======================================================
#  Modbus-RTU 工具函数（从 realtime_sensor_display.py 移植）
# ======================================================

def _modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            lsb = crc & 0x0001
            crc >>= 1
            if lsb:
                crc ^= 0xA001
    return crc


def _build_read_request(dev_addr: int, start_reg: int, reg_count: int) -> bytes:
    frame = struct.pack('>BBHH', dev_addr, 0x03, start_reg, reg_count)
    crc = _modbus_crc16(frame)
    frame += struct.pack('<H', crc)
    return frame


def _verify_response(raw: bytes) -> bool:
    if len(raw) < 4:
        return False
    data_part = raw[:-2]
    crc_received = struct.unpack('<H', raw[-2:])[0]
    crc_calc = _modbus_crc16(data_part)
    return crc_received == crc_calc


def _parse_modbus_response(raw: bytes):
    if not _verify_response(raw):
        return None
    if len(raw) < 5:
        return None
    byte_count = raw[2]
    data_bytes = raw[3:3 + byte_count]
    if len(data_bytes) != byte_count:
        return None
    regs = []
    for i in range(0, len(data_bytes), 2):
        val = struct.unpack('>H', data_bytes[i:i + 2])[0]
        regs.append(val)
    return regs


def _read_wind_sensor(ser, dev_addr: int = 0x01) -> Optional[dict]:
    START_REG, REG_COUNT = 0x0000, 4
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        request = _build_read_request(dev_addr, START_REG, REG_COUNT)
        ser.write(request)
        ser.flush()
        time.sleep(0.06)
        expected_len = 3 + REG_COUNT * 2 + 2
        raw = ser.read(expected_len)
        if len(raw) == 0 or not _verify_response(raw):
            return None
        regs = _parse_modbus_response(raw)
        if regs is None or len(regs) < REG_COUNT:
            return None
        wind_speed = regs[0] / 100.0
        wind_dir = regs[1]
        max_wind_speed = regs[2] / 100.0
        wind_level = regs[3]
        dir_names = ["北", "东北偏北", "东北", "东北偏东",
                     "东", "东南偏东", "东南", "东南偏南",
                     "南", "西南偏南", "西南", "西南偏西",
                     "西", "西北偏西", "西北", "西北偏北", "北"]
        dir_idx = round(wind_dir / 22.5) % 16
        dir_text = dir_names[dir_idx]
        return {
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "wind_dir_text": dir_text,
            "max_wind_speed": max_wind_speed,
            "wind_level": wind_level,
        }
    except (serial.SerialException, Exception):
        return None


def _read_louver_sensor(ser, dev_addr: int = 0x02) -> Optional[dict]:
    """读取百叶箱传感器 — 仅取前3项：温度/湿度/气压"""
    START_REG, REG_COUNT = 0x0000, 3   # 只读前3个寄存器
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        request = _build_read_request(dev_addr, START_REG, REG_COUNT)
        ser.write(request)
        ser.flush()
        time.sleep(0.06)
        expected_len = 3 + REG_COUNT * 2 + 2
        raw = ser.read(expected_len)
        if len(raw) == 0 or not _verify_response(raw):
            return None
        regs = _parse_modbus_response(raw)
        if regs is None or len(regs) < REG_COUNT:
            return None
        temp_raw = struct.unpack('>h', struct.pack('>H', regs[0]))[0]
        temperature = temp_raw / 20.0
        humidity = regs[1] / 10.0
        pressure = regs[2] / 10.0
        return {
            "temperature": temperature,
            "humidity": humidity,
            "pressure": pressure,
        }
    except (serial.SerialException, Exception):
        return None


def _read_rain_sensor(ser, dev_addr: int = 0x03) -> Optional[dict]:
    START_REG, REG_COUNT = 0x0000, 1
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        request = _build_read_request(dev_addr, START_REG, REG_COUNT)
        ser.write(request)
        ser.flush()
        time.sleep(0.06)
        expected_len = 3 + REG_COUNT * 2 + 2
        raw = ser.read(expected_len)
        if len(raw) == 0 or not _verify_response(raw):
            return None
        regs = _parse_modbus_response(raw)
        if regs is None or len(regs) < REG_COUNT:
            return None
        rainfall = regs[0] / 10.0
        return {"rainfall": rainfall}
    except (serial.SerialException, Exception):
        return None


def _build_write_request(dev_addr: int, reg_addr: int, value: int) -> bytes:
    """构造 Modbus-RTU 写单个寄存器请求帧 (功能码 0x06)"""
    frame = struct.pack('>BBHH', dev_addr, 0x06, reg_addr, value)
    crc = _modbus_crc16(frame)
    frame += struct.pack('<H', crc)
    return frame


def _clear_rain_sensor(ser, dev_addr: int = 0x02) -> bool:
    """清除雨量计数据：向寄存器 0x0000 写入 0x005A"""
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        request = _build_write_request(dev_addr, 0x0000, 0x005A)
        ser.write(request)
        ser.flush()
        time.sleep(0.15)
        raw = ser.read(8)
        if len(raw) >= 8 and _verify_response(raw):
            return True
        return False
    except (serial.SerialException, Exception):
        return False


# ======================================================
#  传感器采集线程
# ======================================================

class SensorWorkerThread(QThread):
    """后台线程：打开串口，每 0.5 秒轮询三个 Modbus 传感器"""
    dataReady = pyqtSignal(dict)
    errorOccurred = pyqtSignal(str)
    clearRainDone = pyqtSignal(bool)

    def __init__(self, port: str, baud: int,
                 wind_enabled: bool, wind_addr: int,
                 louver_enabled: bool, louver_addr: int,
                 rain_enabled: bool, rain_addr: int,
                 parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self.wind_enabled = wind_enabled
        self.wind_addr = wind_addr
        self.louver_enabled = louver_enabled
        self.louver_addr = louver_addr
        self.rain_enabled = rain_enabled
        self.rain_addr = rain_addr
        self._running = False
        self._ser = None
        self._pending_clear_rain = False

    def request_clear_rain(self):
        """请求在下次轮询时清除雨量（线程安全）"""
        self._pending_clear_rain = True

    def run(self):
        self._running = True
        try:
            self._ser = serial.Serial(self.port, baudrate=self.baud,
                                      bytesize=8, parity='N', stopbits=1, timeout=1.5)
        except Exception as e:
            self.errorOccurred.emit(f"无法打开串口 {self.port}: {e}")
            return

        counter = 0
        while self._running:
            counter += 1
            timestamp = datetime.now().strftime("%H:%M:%S")

            # 处理清除雨量请求
            if self._pending_clear_rain:
                self._pending_clear_rain = False
                ok = _clear_rain_sensor(self._ser, self.rain_addr)
                self.clearRainDone.emit(ok)

            wind_data = _read_wind_sensor(self._ser, self.wind_addr) if self.wind_enabled else None
            louver_data = _read_louver_sensor(self._ser, self.louver_addr) if self.louver_enabled else None
            rain_data = _read_rain_sensor(self._ser, self.rain_addr) if self.rain_enabled else None

            self.dataReady.emit({
                "counter": counter,
                "timestamp": timestamp,
                "wind": wind_data,
                "louver": louver_data,
                "rain": rain_data,
            })
            time.sleep(0.5)

        if self._ser and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        self.wait(2000)


# ======================================================
#  PyQt5 传感器数据卡片
# ======================================================

class SensorRealtimeCard(QFrame):
    """三485传感器实时数据卡片 — 集成到地面站"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[SensorWorkerThread] = None
        self._running = False
        self._read_count = 0
        self._err_wind = 0
        self._err_louver = 0
        self._err_rain = 0
        self.setup_ui()
        self._refresh_ports()

        # 定时自动刷新串口列表（每2秒检测一次新接入的串口）
        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.timeout.connect(self._auto_refresh_ports)
        self._port_refresh_timer.start(2000)

    def setup_ui(self):
        self.setObjectName("sensorRealtimeCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet("""
            QFrame#sensorRealtimeCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f0f9ff, stop:1 #e6f7ff);
                border: 2px solid #69c0ff;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── 标题栏 ──
        title_layout = QHBoxLayout()
        title = QLabel("📡 三传感器实时数据")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #003a8c; background: transparent;")
        title_layout.addWidget(title)

        self.status_label = QLabel("⏸ 未启动")
        self.status_label.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent; font-weight: 600;")
        title_layout.addStretch()
        title_layout.addWidget(self.status_label)
        layout.addLayout(title_layout)

        # ── 控制栏：串口 + 波特率 + 按钮 ──
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet("QFrame { background-color: rgba(255,255,255,0.7); border: 1px solid #91d5ff; border-radius: 8px; }")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(8, 6, 8, 6)
        ctrl_layout.setSpacing(6)

        ctrl_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self.port_combo.setMaxVisibleItems(5)
        self.port_combo.setStyleSheet("""
            QComboBox {
                padding: 3px 8px;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                background: white;
                font-size: 12px;
                color: #303133;
            }
            QComboBox:hover { border-color: #409EFF; }
            QComboBox QAbstractItemView {
                min-width: 200px;
                outline: none;
                border: 1px solid #91d5ff;
                border-radius: 4px;
                background: white;
                padding: 4px;
                font-size: 12px;
                color: #303133;
                selection-background-color: #ecf5ff;
                selection-color: #1890ff;
            }
            QComboBox QAbstractItemView::item {
                padding: 5px 10px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #f0f9ff;
                color: #0050b3;
            }
        """)
        ctrl_layout.addWidget(self.port_combo)

        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(32)
        refresh_btn.setStyleSheet("QPushButton { border: 1px solid #dcdfe6; border-radius: 4px; background: white; } QPushButton:hover { background: #ecf5ff; }")
        refresh_btn.clicked.connect(self._refresh_ports)
        ctrl_layout.addWidget(refresh_btn)

        ctrl_layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["2400", "4800", "9600", "19200", "38400", "115200"])
        self.baud_combo.setCurrentText("9600")
        self.baud_combo.setMinimumWidth(85)
        self.baud_combo.setStyleSheet("""
            QComboBox {
                padding: 3px 8px;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                background: white;
                font-size: 12px;
                color: #303133;
            }
            QComboBox:hover { border-color: #409EFF; }
            QComboBox QAbstractItemView {
                outline: none;
                border: 1px solid #91d5ff;
                border-radius: 4px;
                background: white;
                font-size: 12px;
                selection-background-color: #ecf5ff;
                selection-color: #1890ff;
            }
            QComboBox QAbstractItemView::item {
                padding: 4px 10px;
                min-height: 22px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #f0f9ff;
                color: #0050b3;
            }
        """)
        ctrl_layout.addWidget(self.baud_combo)

        ctrl_layout.addStretch()

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #67C23A; color: white; border: none; border-radius: 4px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #85ce61; }"
            "QPushButton:disabled { background-color: #c0c4cc; }")
        self.start_btn.clicked.connect(self._start_collection)
        ctrl_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #F56C6C; color: white; border: none; border-radius: 4px; padding: 5px 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #f78989; }"
            "QPushButton:disabled { background-color: #c0c4cc; }")
        self.stop_btn.clicked.connect(self._stop_collection)
        ctrl_layout.addWidget(self.stop_btn)

        layout.addWidget(ctrl_frame)

        # ── 传感器启用 + 地址 ──
        addr_frame = QFrame()
        addr_frame.setStyleSheet("QFrame { background: transparent; }")
        addr_layout = QHBoxLayout(addr_frame)
        addr_layout.setContentsMargins(4, 2, 4, 2)
        addr_layout.setSpacing(8)

        # 风速传感器
        self.wind_cb = QCheckBox("风速传感器")
        self.wind_cb.setChecked(True)
        self.wind_cb.setStyleSheet("QCheckBox { font-weight: 600; color: #0050b3; }")
        addr_layout.addWidget(self.wind_cb)
        addr_layout.addWidget(QLabel("地址:"))
        self.wind_addr_spin = QSpinBox()
        self.wind_addr_spin.setRange(1, 247)
        self.wind_addr_spin.setValue(1)
        self.wind_addr_spin.setFixedWidth(55)
        addr_layout.addWidget(self.wind_addr_spin)

        # 百叶箱传感器
        self.louver_cb = QCheckBox("百叶箱")
        self.louver_cb.setChecked(True)
        self.louver_cb.setStyleSheet("QCheckBox { font-weight: 600; color: #D29922; }")
        addr_layout.addWidget(self.louver_cb)
        addr_layout.addWidget(QLabel("地址:"))
        self.louver_addr_spin = QSpinBox()
        self.louver_addr_spin.setRange(1, 247)
        self.louver_addr_spin.setValue(4)
        self.louver_addr_spin.setFixedWidth(55)
        addr_layout.addWidget(self.louver_addr_spin)

        # 雨量传感器
        self.rain_cb = QCheckBox("雨量传感器")
        self.rain_cb.setChecked(True)
        self.rain_cb.setStyleSheet("QCheckBox { font-weight: 600; color: #0050b3; }")
        addr_layout.addWidget(self.rain_cb)
        addr_layout.addWidget(QLabel("地址:"))
        self.rain_addr_spin = QSpinBox()
        self.rain_addr_spin.setRange(1, 247)
        self.rain_addr_spin.setValue(2)
        self.rain_addr_spin.setFixedWidth(55)
        addr_layout.addWidget(self.rain_addr_spin)

        addr_layout.addStretch()
        layout.addWidget(addr_frame)

        # ── 数据卡片区（三列） ──
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)

        self._add_wind_card(cards_layout)
        self._add_louver_card(cards_layout)
        self._add_rain_card(cards_layout)

        layout.addLayout(cards_layout, 1)

    # ── 风速卡片 ──
    def _add_wind_card(self, parent_layout):
        card = self._make_sensor_box("💨 超声波风速风向")
        inner = card.layout()  # 复用 _make_sensor_box 创建的布局
        inner.setContentsMargins(8, 6, 8, 6)
        inner.setSpacing(4)

        self.wind_labels: Dict[str, QLabel] = {}
        for name, unit, default in [
            ("瞬时风速", "m/s", "0.00"),
            ("风向角度", "°", "0"),
            ("风向描述", "", "—"),
            ("最大风速", "m/s", "0.00"),
            ("风力等级", "级", "0"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet("color: #606266; font-size: 11px; background: transparent;")
            lbl_name.setFixedWidth(60)
            lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl_name)
            val = QLabel(default)
            val.setStyleSheet("font-size: 18px; font-weight: bold; color: #003a8c; background: transparent;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(val, 1)
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet("color: #8b949e; font-size: 11px; background: transparent;")
            unit_lbl.setFixedWidth(36)
            row.addWidget(unit_lbl)
            inner.addLayout(row)
            self.wind_labels[name] = val

        self.wind_err_label = QLabel("")
        self.wind_err_label.setStyleSheet("color: #F56C6C; font-size: 10px; background: transparent;")
        inner.addWidget(self.wind_err_label)

        parent_layout.addWidget(card, 1)

    # ── 百叶箱卡片（仅温度/湿度/气压） ──
    def _add_louver_card(self, parent_layout):
        card = self._make_sensor_box("🌡️ 百叶箱传感器")
        inner = card.layout()  # 复用 _make_sensor_box 创建的布局
        inner.setContentsMargins(8, 6, 8, 6)
        inner.setSpacing(4)

        self.louver_labels: Dict[str, QLabel] = {}
        for name, unit, default in [
            ("温度", "°C", "0.0"),
            ("湿度", "%RH", "0.0"),
            ("气压", "kPa", "0.0"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet("color: #606266; font-size: 11px; background: transparent;")
            lbl_name.setFixedWidth(60)
            lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl_name)
            val = QLabel(default)
            val.setStyleSheet("font-size: 18px; font-weight: bold; color: #ad6800; background: transparent;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(val, 1)
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet("color: #8b949e; font-size: 11px; background: transparent;")
            unit_lbl.setFixedWidth(40)
            row.addWidget(unit_lbl)
            inner.addLayout(row)
            self.louver_labels[name] = val

        self.louver_err_label = QLabel("")
        self.louver_err_label.setStyleSheet("color: #F56C6C; font-size: 10px; background: transparent;")
        inner.addWidget(self.louver_err_label)

        parent_layout.addWidget(card, 1)

    # ── 雨量卡片 ──
    def _add_rain_card(self, parent_layout):
        card = self._make_sensor_box("🌧️ 全不锈钢雨量传感器")
        inner = card.layout()  # 复用 _make_sensor_box 创建的布局
        inner.setContentsMargins(8, 6, 8, 6)
        inner.setSpacing(4)

        self.rain_labels: Dict[str, QLabel] = {}
        for name, unit, default in [
            ("累计雨量", "mm", "0.0"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet("color: #606266; font-size: 11px; background: transparent;")
            lbl_name.setFixedWidth(60)
            lbl_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl_name)
            val = QLabel(default)
            val.setStyleSheet("font-size: 22px; font-weight: bold; color: #003a8c; background: transparent;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(val, 1)
            unit_lbl = QLabel(unit)
            unit_lbl.setStyleSheet("color: #8b949e; font-size: 11px; background: transparent;")
            unit_lbl.setFixedWidth(36)
            row.addWidget(unit_lbl)
            inner.addLayout(row)
            self.rain_labels[name] = val

        self.rain_err_label = QLabel("")
        self.rain_err_label.setStyleSheet("color: #F56C6C; font-size: 10px; background: transparent;")
        inner.addWidget(self.rain_err_label)

        # 清除雨量按钮
        self.clear_rain_btn = QPushButton("🧹 清除雨量")
        self.clear_rain_btn.setEnabled(False)
        self.clear_rain_btn.setStyleSheet(
            "QPushButton { background-color: #E6A23C; color: white; border: none; border-radius: 4px; "
            "padding: 4px 10px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #ebb563; }"
            "QPushButton:disabled { background-color: #c0c4cc; }")
        self.clear_rain_btn.clicked.connect(self._clear_rainfall)
        inner.addWidget(self.clear_rain_btn)

        parent_layout.addWidget(card, 1)

    def _make_sensor_box(self, title_text: str) -> QFrame:
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,0.8);
                border: 1px solid #91d5ff;
                border-radius: 10px;
            }
        """)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        title_lbl = QLabel(f"  {title_text}")
        title_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #003a8c; background: transparent; padding: 4px 0;")
        layout.addWidget(title_lbl)
        return box

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
        """自动刷新串口列表 — 仅在未采集时更新，避免干扰正在使用的串口"""
        if self._running:
            return
        if serial is None:
            return
        current = self.port_combo.currentText()
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return
        # 只在端口列表变化时更新（避免频繁清空重建导致闪烁）
        existing = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
        if set(ports) != set(existing):
            self.port_combo.clear()
            self.port_combo.addItems(ports)
            if current and current in ports:
                self.port_combo.setCurrentText(current)
            elif ports:
                self.port_combo.setCurrentIndex(0)

    # ── 开始/停止采集 ──
    def _start_collection(self):
        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "串口未设置", "请先选择 RS485 集线器串口！")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            baud = 9600

        wind_enabled = self.wind_cb.isChecked()
        louver_enabled = self.louver_cb.isChecked()
        rain_enabled = self.rain_cb.isChecked()

        if not any([wind_enabled, louver_enabled, rain_enabled]):
            QMessageBox.warning(self, "无传感器", "至少需要启用一个传感器才能开始采集！")
            return

        wind_addr = self.wind_addr_spin.value()
        louver_addr = self.louver_addr_spin.value()
        rain_addr = self.rain_addr_spin.value()

        # 检查地址冲突
        enabled = []
        if wind_enabled:
            enabled.append(("风速传感器", wind_addr))
        if louver_enabled:
            enabled.append(("百叶箱传感器", louver_addr))
        if rain_enabled:
            enabled.append(("雨量传感器", rain_addr))
        seen = {}
        for name, addr in enabled:
            if addr in seen:
                QMessageBox.warning(self, "地址冲突",
                    f"{name} 与 {seen[addr]} 地址冲突 (均为 0x{addr:02X})！")
                return
            seen[addr] = name

        self._running = True
        self._read_count = 0
        self._err_wind = 0
        self._err_louver = 0
        self._err_rain = 0

        self.worker = SensorWorkerThread(
            port=port, baud=baud,
            wind_enabled=wind_enabled, wind_addr=wind_addr,
            louver_enabled=louver_enabled, louver_addr=louver_addr,
            rain_enabled=rain_enabled, rain_addr=rain_addr,
            parent=self)
        self.worker.dataReady.connect(self._on_data_ready)
        self.worker.errorOccurred.connect(self._on_error)
        self.worker.clearRainDone.connect(self._on_clear_rain_done)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_rain_btn.setEnabled(True)
        self.port_combo.setEnabled(False)
        self.baud_combo.setEnabled(False)
        self.wind_cb.setEnabled(False)
        self.louver_cb.setEnabled(False)
        self.rain_cb.setEnabled(False)
        self.wind_addr_spin.setEnabled(False)
        self.louver_addr_spin.setEnabled(False)
        self.rain_addr_spin.setEnabled(False)

        sensors = []
        if wind_enabled:
            sensors.append(f"风速(0x{wind_addr:02X})")
        if louver_enabled:
            sensors.append(f"百叶箱(0x{louver_addr:02X})")
        if rain_enabled:
            sensors.append(f"雨量(0x{rain_addr:02X})")
        self.status_label.setText(f"▶ 采集中 — {port} @{baud}")
        self.status_label.setStyleSheet("font-size: 12px; color: #67C23A; background: transparent; font-weight: 600;")

    def _stop_collection(self):
        self._running = False
        if self.worker:
            self.worker.stop()
            self.worker = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_rain_btn.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.wind_cb.setEnabled(True)
        self.louver_cb.setEnabled(True)
        self.rain_cb.setEnabled(True)
        self.wind_addr_spin.setEnabled(True)
        self.louver_addr_spin.setEnabled(True)
        self.rain_addr_spin.setEnabled(True)

        summary = f"⏸ 已停止 — 共采集 {self._read_count} 次"
        if self._err_wind or self._err_louver or self._err_rain:
            parts = []
            if self._err_wind:
                parts.append(f"风速失败{self._err_wind}次")
            if self._err_louver:
                parts.append(f"百叶箱失败{self._err_louver}次")
            if self._err_rain:
                parts.append(f"雨量失败{self._err_rain}次")
            summary += " | " + " ".join(parts)
        self.status_label.setText(summary)
        self.status_label.setStyleSheet("font-size: 12px; color: #8b949e; background: transparent; font-weight: 600;")

    def _clear_rainfall(self):
        """请求后台线程向雨量传感器发送清除命令"""
        if not self.worker:
            return
        self.clear_rain_btn.setEnabled(False)
        self.clear_rain_btn.setText("⏳ 清除中...")
        self.worker.request_clear_rain()

    def _on_clear_rain_done(self, ok: bool):
        """清除雨量命令执行结果回调"""
        if ok:
            self.rain_err_label.setText("✅ 雨量已清除")
            self.rain_err_label.setStyleSheet("color: #67C23A; font-size: 10px; background: transparent;")
        else:
            self.rain_err_label.setText("❌ 清除失败")
            self.rain_err_label.setStyleSheet("color: #F56C6C; font-size: 10px; background: transparent;")
        self.clear_rain_btn.setEnabled(True)
        self.clear_rain_btn.setText("🧹 清除雨量")
        # 1.5秒后恢复错误标签
        QTimer.singleShot(1500, lambda: self.rain_err_label.setText(""))

    def _on_data_ready(self, data: dict):
        self._read_count = data.get("counter", self._read_count)

        # 更新风速数据
        wind = data.get("wind")
        if wind:
            self._update_label(self.wind_labels, "瞬时风速", f"{wind['wind_speed']:.2f}")
            self._update_label(self.wind_labels, "风向角度", str(wind['wind_dir']))
            self._update_label(self.wind_labels, "风向描述", wind['wind_dir_text'])
            self._update_label(self.wind_labels, "最大风速", f"{wind['max_wind_speed']:.2f}")
            self._update_label(self.wind_labels, "风力等级", str(wind['wind_level']))
            self.wind_err_label.setText("")
        else:
            self._err_wind += 1
            self.wind_err_label.setText(f"读取失败 ({self._err_wind})")

        # 更新百叶箱数据（仅温度/湿度/气压）
        louver = data.get("louver")
        if louver:
            self._update_label(self.louver_labels, "温度", f"{louver['temperature']:.1f}")
            self._update_label(self.louver_labels, "湿度", f"{louver['humidity']:.1f}")
            self._update_label(self.louver_labels, "气压", f"{louver['pressure']:.1f}")
            self.louver_err_label.setText("")
        else:
            self._err_louver += 1
            self.louver_err_label.setText(f"读取失败 ({self._err_louver})")

        # 更新雨量数据
        rain = data.get("rain")
        if rain:
            self._update_label(self.rain_labels, "累计雨量", f"{rain['rainfall']:.1f}")
            self.rain_err_label.setText("")
        else:
            self._err_rain += 1
            self.rain_err_label.setText(f"读取失败 ({self._err_rain})")

    def _update_label(self, label_dict: dict, key: str, text: str):
        if key in label_dict:
            label_dict[key].setText(text)

    def _on_error(self, msg: str):
        self.status_label.setText(f"❌ {msg}")
        self.status_label.setStyleSheet("font-size: 12px; color: #F56C6C; background: transparent; font-weight: 600;")
        self._stop_collection()

    def stop_and_cleanup(self):
        """外部调用的安全停止方法"""
        self._port_refresh_timer.stop()
        if self._running:
            self._stop_collection()
