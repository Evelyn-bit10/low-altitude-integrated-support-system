"""三485传感器数据卡片（PySide6）—— 底部面板右侧展示。

Modbus-RTU 读取三类传感器：
- 超声波风速风向传感器 (9600bps)
- 百叶箱传感器 (温度/湿度/气压/光照/PM/噪声/CO₂/TSP, 9600bps)
- 全不锈钢雨量传感器 (9600bps)

后台线程每 0.5 秒轮询一次，通过信号更新 UI。
"""
from __future__ import annotations

import struct
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ═══════════════════════════════════════════════════════
#  Modbus-RTU 工具函数
# ═══════════════════════════════════════════════════════

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


def _parse_modbus_response(raw: bytes) -> Optional[List[int]]:
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


def _build_write_request(dev_addr: int, reg_addr: int, value: int) -> bytes:
    frame = struct.pack('>BBHH', dev_addr, 0x06, reg_addr, value)
    crc = _modbus_crc16(frame)
    frame += struct.pack('<H', crc)
    return frame


# ═══════════════════════════════════════════════════════
#  传感器读取
# ═══════════════════════════════════════════════════════

def read_wind_sensor(port: str) -> Optional[dict]:
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 4
    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=0.8) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            request = _build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()
            time.sleep(0.03)
            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)
            if len(raw) == 0:
                return None
            if not _verify_response(raw):
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


def read_louver_sensor(port: str) -> Optional[dict]:
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 13
    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=0.8) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            request = _build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()
            time.sleep(0.03)
            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)
            if len(raw) == 0:
                return None
            if not _verify_response(raw):
                return None
            regs = _parse_modbus_response(raw)
            if regs is None or len(regs) < REG_COUNT:
                return None
            temp_raw = struct.unpack('>h', struct.pack('>H', regs[0]))[0]
            temperature = temp_raw / 20.0
            humidity = regs[1] / 10.0
            pressure = regs[2] / 10.0
            light_raw = (regs[3] << 16) | regs[4]
            light = light_raw / 10.0
            pm25 = regs[5]
            pm10 = regs[6]
            noise = regs[7] / 10.0
            co2 = regs[8]
            tsp = regs[9]
            return {
                "temperature": temperature,
                "humidity": humidity,
                "pressure": pressure,
                "light": light,
                "pm25": pm25,
                "pm10": pm10,
                "noise": noise,
                "co2": co2,
                "tsp": tsp,
            }
    except (serial.SerialException, Exception):
        return None


def read_rain_sensor(port: str) -> Optional[dict]:
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 1
    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=0.8) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            request = _build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()
            time.sleep(0.03)
            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)
            if len(raw) == 0:
                return None
            if not _verify_response(raw):
                return None
            regs = _parse_modbus_response(raw)
            if regs is None or len(regs) < REG_COUNT:
                return None
            rainfall = regs[0] / 10.0
            return {"rainfall": rainfall}
    except (serial.SerialException, Exception):
        return None


def clear_rain_data(port: str, dev_addr: int = 0x01, baud: int = 9600) -> bool:
    try:
        with serial.Serial(port, baudrate=baud, bytesize=8,
                           parity='N', stopbits=1, timeout=1.5) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            request = _build_write_request(dev_addr, 0x0000, 0x005A)
            ser.write(request)
            ser.flush()
            time.sleep(0.1)
            raw = ser.read(8)
            if len(raw) >= 8 and _verify_response(raw):
                return True
            return False
    except (serial.SerialException, Exception):
        return False


# ═══════════════════════════════════════════════════════
#  后台采集线程
# ═══════════════════════════════════════════════════════

class SensorWorker(QThread):
    """后台线程：每 0.5 秒采集三个传感器，通过信号发送数据。"""
    data_ready = Signal(dict)

    def __init__(self, wind_port: str, louver_port: str, rain_port: str, parent=None):
        super().__init__(parent)
        self.wind_port = wind_port
        self.louver_port = louver_port
        self.rain_port = rain_port
        self._running = False
        self._counter = 0

    def run(self) -> None:
        self._running = True
        while self._running:
            self._counter += 1
            timestamp = datetime.now().strftime("%H:%M:%S")

            wind_data = None if self.wind_port == "无" else read_wind_sensor(self.wind_port)
            louver_data = None if self.louver_port == "无" else read_louver_sensor(self.louver_port)
            rain_data = None if self.rain_port == "无" else read_rain_sensor(self.rain_port)

            self.data_ready.emit({
                "counter": self._counter,
                "timestamp": timestamp,
                "wind": wind_data,
                "louver": louver_data,
                "rain": rain_data,
                "wind_skip": self.wind_port == "无",
                "louver_skip": self.louver_port == "无",
                "rain_skip": self.rain_port == "无",
            })
            # 每 0.5 秒检查一次停止标志
            for _ in range(50):
                if not self._running:
                    break
                self.msleep(10)

    def stop(self) -> None:
        self._running = False


# ═══════════════════════════════════════════════════════
#  GUI 卡片
# ═══════════════════════════════════════════════════════

class GcsSensorCard(QFrame):
    """传感器数据卡片，用于底部面板右侧。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("gcsSensorCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(220)

        self._worker: Optional[SensorWorker] = None
        self._running = False
        self._read_count = 0
        self._wind_error_count = 0
        self._louver_error_count = 0
        self._rain_error_count = 0

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(4)

        # ── 标题行 ──
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel("📡 传感器")
        title.setObjectName("gcsSensorTitle")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #e6edf3;")

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #8b949e; font-size: 12px; font-weight: bold;")
        self._status_label = QLabel("未连接")
        self._status_label.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: bold;")

        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self._status_dot)
        title_row.addWidget(self._status_label)
        root.addLayout(title_row)

        # ── 串口选择行 ──
        port_row = QGridLayout()
        port_row.setSpacing(3)

        lbl_wind = QLabel("风速")
        lbl_wind.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold;")
        lbl_louver = QLabel("百叶箱")
        lbl_louver.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold;")
        lbl_rain = QLabel("雨量")
        lbl_rain.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: bold;")

        self._wind_combo = QComboBox()
        self._wind_combo.setEditable(False)
        self._wind_combo.setMinimumWidth(80)
        self._wind_combo.setStyleSheet(
            "QComboBox { font-size: 10px; background: #21262d; color: #e6edf3; border: 1px solid #30363d; "
            "border-radius: 3px; padding: 2px 4px; }"
            "QComboBox::drop-down { border: none; }"
        )

        self._louver_combo = QComboBox()
        self._louver_combo.setEditable(False)
        self._louver_combo.setMinimumWidth(80)
        self._louver_combo.setStyleSheet(self._wind_combo.styleSheet())

        self._rain_combo = QComboBox()
        self._rain_combo.setEditable(False)
        self._rain_combo.setMinimumWidth(80)
        self._rain_combo.setStyleSheet(self._wind_combo.styleSheet())

        port_row.addWidget(lbl_wind, 0, 0)
        port_row.addWidget(self._wind_combo, 0, 1)
        port_row.addWidget(lbl_louver, 0, 2)
        port_row.addWidget(self._louver_combo, 0, 3)
        port_row.addWidget(lbl_rain, 1, 0)
        port_row.addWidget(self._rain_combo, 1, 1)

        # 按钮
        self._start_btn = QPushButton("▶ 开始")
        self._start_btn.setStyleSheet(
            "QPushButton { background: #3fb950; color: #000; font-size: 10px; font-weight: bold; "
            "border: none; border-radius: 3px; padding: 3px 8px; }"
            "QPushButton:hover { background: #2ea043; }"
            "QPushButton:disabled { background: #30363d; color: #484f58; }"
        )
        self._start_btn.clicked.connect(self._start)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "QPushButton { background: #f85149; color: #fff; font-size: 10px; font-weight: bold; "
            "border: none; border-radius: 3px; padding: 3px 8px; }"
            "QPushButton:hover { background: #da3633; }"
            "QPushButton:disabled { background: #30363d; color: #484f58; }"
        )
        self._stop_btn.clicked.connect(self._stop)

        self._refresh_btn = QPushButton("🔄")
        self._refresh_btn.setToolTip("刷新串口")
        self._refresh_btn.setFixedSize(26, 22)
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #58a6ff; font-size: 11px; "
            "border: 1px solid #30363d; border-radius: 3px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        self._refresh_btn.clicked.connect(self._refresh_ports)

        port_row.addWidget(self._start_btn, 1, 2)
        port_row.addWidget(self._stop_btn, 1, 3)
        port_row.addWidget(self._refresh_btn, 1, 4)
        root.addLayout(port_row)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #30363d; max-height: 1px; border: none;")
        root.addWidget(sep)

        # ── 数据网格 ──
        data_grid = QGridLayout()
        data_grid.setSpacing(1)
        data_grid.setContentsMargins(0, 0, 0, 0)

        self._value_labels: Dict[str, QLabel] = {}

        fields = [
            # (key, label, unit, row, col)
            ("风速",   "风速",   "m/s",    0, 0),
            ("风向",   "风向",   "",       0, 1),
            ("风力",   "风力",   "级",     0, 2),
            ("温度",   "温度",   "°C",     1, 0),
            ("湿度",   "湿度",   "%",       1, 1),
            ("气压",   "气压",   "kPa",    1, 2),
            ("光照",   "光照",   "Lux",    2, 0),
            ("雨量",   "雨量",   "mm",     2, 1),
        ]

        style_fixed = (
            "QLabel { font-family: 'Consolas', 'SimSun'; font-size: 14px; font-weight: bold; "
            "color: #e6edf3; background: #161b22; border: 1px solid #30363d; "
            "border-radius: 3px; padding: 2px 4px; min-width: 55px; }"
        )

        for key, label_text, unit, row, col in fields:
            container = QVBoxLayout()
            container.setSpacing(0)
            container.setContentsMargins(0, 0, 0, 0)

            header_lbl = QLabel(label_text)
            header_lbl.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
            header_lbl.setStyleSheet(
                "font-size: 9px; font-weight: bold; color: #8b949e; padding: 0 2px; background: transparent; border: none;"
            )

            val = QLabel("--")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet(style_fixed)
            val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            unit_lbl = QLabel(f" {unit}" if unit else "")
            unit_lbl.setStyleSheet(
                "font-size: 9px; color: #8b949e; background: transparent; border: none;"
            )

            row_widget = QHBoxLayout()
            row_widget.setSpacing(2)
            row_widget.setContentsMargins(0, 0, 0, 0)
            row_widget.addWidget(val, 1)
            if unit:
                row_widget.addWidget(unit_lbl)

            container.addWidget(header_lbl)
            container.addLayout(row_widget)

            wrapper = QWidget()
            wrapper.setLayout(container)
            data_grid.addWidget(wrapper, row, col)

            self._value_labels[key] = val

        root.addLayout(data_grid, 1)

        # ── 错误标签 ──
        self._error_label = QLabel("")
        self._error_label.setStyleSheet("font-size: 9px; color: #f85149;")
        self._error_label.setWordWrap(True)
        root.addWidget(self._error_label)

        # 初始刷新串口
        self._refresh_ports()

    # ── 串口 ──────────────────────────────────────────

    def _refresh_ports(self) -> None:
        # 基础选项：无 + COM1~COM5
        base = ["无"] + [f"COM{i}" for i in range(1, 6)]
        if HAS_SERIAL:
            try:
                detected = [p.device for p in serial.tools.list_ports.comports()]
            except Exception:
                detected = []
            # 合并检测到的串口（去重，保持顺序）
            for d in detected:
                if d not in base:
                    base.append(d)
        choices = base

        current_wind = self._wind_combo.currentText()
        current_louver = self._louver_combo.currentText()
        current_rain = self._rain_combo.currentText()

        for combo in (self._wind_combo, self._louver_combo, self._rain_combo):
            combo.clear()
            combo.addItems(choices)

        if current_wind in choices:
            self._wind_combo.setCurrentText(current_wind)
        elif len(choices) > 1:
            self._wind_combo.setCurrentIndex(1)
        if current_louver in choices:
            self._louver_combo.setCurrentText(current_louver)
        elif len(choices) > 2:
            self._louver_combo.setCurrentIndex(2)
        elif len(choices) > 1:
            self._louver_combo.setCurrentIndex(1)
        if current_rain in choices:
            self._rain_combo.setCurrentText(current_rain)
        elif len(choices) > 3:
            self._rain_combo.setCurrentIndex(3)
        elif len(choices) > 1:
            self._rain_combo.setCurrentIndex(1)

    # ── 启动/停止 ─────────────────────────────────────

    def _start(self) -> None:
        wind_port = self._wind_combo.currentText().strip()
        louver_port = self._louver_combo.currentText().strip()
        rain_port = self._rain_combo.currentText().strip()

        if not wind_port or not louver_port or not rain_port:
            return

        real_ports = [p for p in [wind_port, louver_port, rain_port] if p != "无"]
        if not real_ports:
            return
        if len(real_ports) != len(set(real_ports)):
            return

        self._running = True
        self._read_count = 0
        self._wind_error_count = 0
        self._louver_error_count = 0
        self._rain_error_count = 0

        self._wind_skip = wind_port == "无"
        self._louver_skip = louver_port == "无"
        self._rain_skip = rain_port == "无"

        self._worker = SensorWorker(wind_port, louver_port, rain_port)
        self._worker.data_ready.connect(self._on_data)
        self._worker.start()

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        for c in (self._wind_combo, self._louver_combo, self._rain_combo):
            c.setEnabled(False)

        self._status_dot.setStyleSheet("color: #3fb950; font-size: 12px;")
        self._status_label.setText("采集中")
        self._status_label.setStyleSheet("color: #3fb950; font-size: 11px;")

    def _stop(self) -> None:
        self._running = False
        if self._worker:
            self._worker.stop()
            self._worker.wait(2000)
            self._worker = None

        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        for c in (self._wind_combo, self._louver_combo, self._rain_combo):
            c.setEnabled(True)

        self._status_dot.setStyleSheet("color: #8b949e; font-size: 12px;")
        self._status_label.setText("已停止")
        self._status_label.setStyleSheet("color: #8b949e; font-size: 11px;")

    # ── 数据更新 ──────────────────────────────────────

    def _on_data(self, data: dict) -> None:
        self._read_count = data["counter"]

        wind = data.get("wind")
        louver = data.get("louver")
        rain = data.get("rain")
        wind_skip = data.get("wind_skip", False)
        louver_skip = data.get("louver_skip", False)
        rain_skip = data.get("rain_skip", False)

        # 风速
        if wind:
            self._value_labels["风速"].setText(f"{wind['wind_speed']:.1f}")
            self._value_labels["风向"].setText(wind['wind_dir_text'])
            self._value_labels["风力"].setText(f"{wind['wind_level']:.0f}")
        elif wind_skip:
            for k in ("风速", "风向", "风力"):
                self._value_labels[k].setText("—")
        else:
            self._wind_error_count += 1

        # 百叶箱
        if louver:
            self._value_labels["温度"].setText(f"{louver['temperature']:.1f}")
            self._value_labels["湿度"].setText(f"{louver['humidity']:.0f}")
            self._value_labels["气压"].setText(f"{louver['pressure']:.1f}")
            self._value_labels["光照"].setText(f"{louver['light']:.0f}")
        elif louver_skip:
            for k in ("温度", "湿度", "气压", "光照"):
                self._value_labels[k].setText("—")
        else:
            self._louver_error_count += 1

        # 雨量
        if rain:
            self._value_labels["雨量"].setText(f"{rain['rainfall']:.1f}")
        elif rain_skip:
            self._value_labels["雨量"].setText("—")
        else:
            self._rain_error_count += 1

        # 错误摘要
        errors = []
        if self._wind_error_count:
            errors.append(f"风速×{self._wind_error_count}")
        if self._louver_error_count:
            errors.append(f"百叶箱×{self._louver_error_count}")
        if self._rain_error_count:
            errors.append(f"雨量×{self._rain_error_count}")
        self._error_label.setText("  ".join(errors) if errors else "")
