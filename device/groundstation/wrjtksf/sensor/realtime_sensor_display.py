#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时三485传感器数据显示面板 (Modbus-RTU)
==========================================
- 独立GUI窗口，输入"开始"开始采集，输入"结束"停止采集
- 手动输入风速传感器串口、温度传感器串口、雨量传感器串口
- 每 0.5 秒更新一次全部传感器数据
- 风速/风向/风级 以超声波风速传感器 (9600bps) 为准
- 温度/湿度/气压/光照/PM2.5/PM10/噪声/CO₂/TSP 以百叶箱传感器 (9600bps) 为准
- 雨量 以全不锈钢雨量传感器 (9600bps) 为准，支持清除雨量

依赖: pyserial (pip install pyserial)
GUI: tkinter (Python 自带)
"""

import struct
import time
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ── 串口 ──────────────────────────────────────────────
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("错误：请先安装 pyserial → pip install pyserial")
    sys.exit(1)


# ======================================================
#  Modbus-RTU 工具函数
# ======================================================

def modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            lsb = crc & 0x0001
            crc >>= 1
            if lsb:
                crc ^= 0xA001
    return crc


def build_read_request(dev_addr: int, start_reg: int, reg_count: int) -> bytes:
    frame = struct.pack('>BBHH', dev_addr, 0x03, start_reg, reg_count)
    crc = modbus_crc16(frame)
    frame += struct.pack('<H', crc)
    return frame


def verify_response(raw: bytes) -> bool:
    if len(raw) < 4:
        return False
    data_part = raw[:-2]
    crc_received = struct.unpack('<H', raw[-2:])[0]
    crc_calc = modbus_crc16(data_part)
    return crc_received == crc_calc


def parse_modbus_response(raw: bytes) -> Optional[List[int]]:
    if not verify_response(raw):
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


def build_write_request(dev_addr: int, reg_addr: int, value: int) -> bytes:
    """
    构造 Modbus-RTU 写单个寄存器请求帧 (功能码 0x06)。
    :param dev_addr: 设备地址 (1-247)
    :param reg_addr: 寄存器地址
    :param value:     写入值 (16 位)
    :return: 完整请求帧 (bytes)
    """
    frame = struct.pack('>BBHH', dev_addr, 0x06, reg_addr, value)
    crc = modbus_crc16(frame)
    frame += struct.pack('<H', crc)
    return frame


def clear_rain_data(port: str, dev_addr: int = 0x01, baud: int = 9600) -> bool:
    """
    清除雨量计数据：向寄存器 0x0000 写入 0x005A。
    :return: 成功返回 True, 失败返回 False
    """
    try:
        with serial.Serial(port, baudrate=baud, bytesize=8,
                           parity='N', stopbits=1, timeout=1.5) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            request = build_write_request(dev_addr, 0x0000, 0x005A)
            ser.write(request)
            ser.flush()
            time.sleep(0.1)
            # 读取响应确认
            raw = ser.read(8)
            if len(raw) >= 8 and verify_response(raw):
                return True
            return False
    except (serial.SerialException, Exception):
        return False


# ======================================================
#  传感器读取
# ======================================================

def read_wind_sensor(port: str) -> Optional[dict]:
    """读取超声波风速风向传感器 (9600bps, 地址 0x01)"""
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 4

    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=1.5) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            request = build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()

            time.sleep(0.05)

            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)

            if len(raw) == 0:
                return None
            if not verify_response(raw):
                return None

            regs = parse_modbus_response(raw)
            if regs is None or len(regs) < REG_COUNT:
                return None

            wind_speed = regs[0] / 100.0
            wind_dir = regs[1]
            max_wind_speed = regs[2] / 100.0
            wind_level = regs[3]

            # 风向文字
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
    """读取百叶箱传感器 (9600bps, 地址 0x01) - 温度/湿度/气压/光照/PM/噪声/CO₂/TSP"""
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 13

    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=1.5) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            request = build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()

            time.sleep(0.05)

            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)

            if len(raw) == 0:
                return None
            if not verify_response(raw):
                return None

            regs = parse_modbus_response(raw)
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
    """读取全不锈钢雨量传感器 (9600bps, 地址 0x01)"""
    DEV_ADDR = 0x01
    BAUD = 9600
    START_REG = 0x0000
    REG_COUNT = 1

    try:
        with serial.Serial(port, baudrate=BAUD, bytesize=8,
                           parity='N', stopbits=1, timeout=1.5) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            request = build_read_request(DEV_ADDR, START_REG, REG_COUNT)
            ser.write(request)
            ser.flush()

            time.sleep(0.05)

            expected_len = 3 + REG_COUNT * 2 + 2
            raw = ser.read(expected_len)

            if len(raw) == 0:
                return None
            if not verify_response(raw):
                return None

            regs = parse_modbus_response(raw)
            if regs is None or len(regs) < REG_COUNT:
                return None

            # 雨量值: 扩大10倍 → ÷10 → mm
            rainfall = regs[0] / 10.0

            return {
                "rainfall": rainfall,
            }
    except (serial.SerialException, Exception):
        return None


# ======================================================
#  传感器采集线程
# ======================================================

class SensorWorker(threading.Thread):
    """后台线程：每 0.5 秒采集三个传感器，通过队列发送给 GUI"""

    def __init__(self, wind_port: str, louver_port: str, rain_port: str, data_queue: queue.Queue):
        super().__init__(daemon=True)
        self.wind_port = wind_port
        self.louver_port = louver_port
        self.rain_port = rain_port
        self.data_queue = data_queue
        self.running = False
        self.counter = 0

    def run(self):
        self.running = True
        while self.running:
            self.counter += 1
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # 读取风速传感器（"无" 表示跳过）
            wind_data = None if self.wind_port == "无" else read_wind_sensor(self.wind_port)

            # 读取百叶箱传感器（"无" 表示跳过）
            louver_data = None if self.louver_port == "无" else read_louver_sensor(self.louver_port)

            # 读取雨量传感器（"无" 表示跳过）
            rain_data = None if self.rain_port == "无" else read_rain_sensor(self.rain_port)

            # 打包数据发送到 GUI
            self.data_queue.put({
                "counter": self.counter,
                "timestamp": timestamp,
                "wind": wind_data,
                "louver": louver_data,
                "rain": rain_data,
                "wind_skip": self.wind_port == "无",
                "louver_skip": self.louver_port == "无",
                "rain_skip": self.rain_port == "无",
            })

            # 精确等待 0.5s（减去读取耗时的大致补偿）
            time.sleep(0.5)

    def stop(self):
        self.running = False


# ======================================================
#  GUI 主窗口
# ======================================================

class SensorDisplayApp:
    """实时传感器数据显示面板"""

    # 颜色方案
    BG_COLOR = "#0D1117"
    PANEL_BG = "#161B22"
    CARD_BG = "#21262D"
    BORDER_COLOR = "#30363D"
    TEXT_COLOR = "#E6EDF3"
    TEXT_SECONDARY = "#8B949E"
    ACCENT_GREEN = "#3FB950"
    ACCENT_BLUE = "#58A6FF"
    ACCENT_YELLOW = "#D29922"
    ACCENT_RED = "#F85149"
    ACCENT_ORANGE = "#DB6D28"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("实时传感器数据面板 — 三485传感器监控")
        self.root.geometry("1180x820")
        self.root.configure(bg=self.BG_COLOR)
        self.root.minsize(1050, 700)

        # 数据队列
        self.data_queue = queue.Queue()
        self.worker: Optional[SensorWorker] = None
        self.running = False

        # 累计统计
        self.read_count = 0
        self.wind_error_count = 0
        self.louver_error_count = 0
        self.rain_error_count = 0
        self.last_wind_data: Optional[dict] = None
        self.last_louver_data: Optional[dict] = None
        self.last_rain_data: Optional[dict] = None

        self._build_ui()
        self._bind_events()

    # ── 构建界面 ──────────────────────────────────────

    def _build_ui(self):
        # 主容器
        main_frame = tk.Frame(self.root, bg=self.BG_COLOR)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # ── 标题栏 ──
        title_frame = tk.Frame(main_frame, bg=self.BG_COLOR)
        title_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(title_frame, text="📡 三485传感器实时监控面板",
                 font=("Microsoft YaHei", 18, "bold"),
                 fg=self.TEXT_COLOR, bg=self.BG_COLOR).pack(side=tk.LEFT)
        self.status_indicator = tk.Canvas(title_frame, width=16, height=16,
                                          bg=self.BG_COLOR, highlightthickness=0)
        self.status_indicator.pack(side=tk.RIGHT, padx=(10, 0))
        self._draw_indicator("gray")
        self.status_label = tk.Label(title_frame, text="未连接",
                                     font=("Microsoft YaHei", 11),
                                     fg=self.TEXT_SECONDARY, bg=self.BG_COLOR)
        self.status_label.pack(side=tk.RIGHT)

        # ── 控制面板 ──
        self.control_panel = tk.Frame(main_frame, bg=self.PANEL_BG,
                                      highlightbackground=self.BORDER_COLOR,
                                      highlightthickness=1)
        self.control_panel.pack(fill=tk.X, pady=(0, 8))

        ctrl_inner = tk.Frame(self.control_panel, bg=self.PANEL_BG)
        ctrl_inner.pack(fill=tk.X, padx=14, pady=10)

        # 风速传感器串口
        tk.Label(ctrl_inner, text="风速传感器串口:",
                 font=("Microsoft YaHei", 11),
                 fg=self.TEXT_COLOR, bg=self.PANEL_BG).grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=4)
        self.wind_port_var = tk.StringVar(value="")
        self.wind_port_combo = ttk.Combobox(ctrl_inner, textvariable=self.wind_port_var,
                                            width=14, font=("Consolas", 11),
                                            state="normal")
        self.wind_port_combo.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=4)

        # 温度传感器串口
        tk.Label(ctrl_inner, text="温度传感器串口:",
                 font=("Microsoft YaHei", 11),
                 fg=self.TEXT_COLOR, bg=self.PANEL_BG).grid(
            row=0, column=2, sticky="e", padx=(0, 6), pady=4)
        self.louver_port_var = tk.StringVar(value="")
        self.louver_port_combo = ttk.Combobox(ctrl_inner, textvariable=self.louver_port_var,
                                              width=14, font=("Consolas", 11),
                                              state="normal")
        self.louver_port_combo.grid(row=0, column=3, sticky="w", padx=(0, 14), pady=4)

        # 雨量传感器串口 (row 1)
        tk.Label(ctrl_inner, text="雨量传感器串口:",
                 font=("Microsoft YaHei", 11),
                 fg=self.TEXT_COLOR, bg=self.PANEL_BG).grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        self.rain_port_var = tk.StringVar(value="")
        self.rain_port_combo = ttk.Combobox(ctrl_inner, textvariable=self.rain_port_var,
                                            width=14, font=("Consolas", 11),
                                            state="normal")
        self.rain_port_combo.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=4)

        # 清除雨量按钮
        self.clear_rain_btn = tk.Button(ctrl_inner, text="🧹 清除雨量",
                                        font=("Microsoft YaHei", 10),
                                        bg=self.CARD_BG, fg=self.ACCENT_ORANGE,
                                        activebackground="#30363D", activeforeground=self.ACCENT_ORANGE,
                                        relief=tk.FLAT, cursor="hand2",
                                        command=self._clear_rainfall)
        self.clear_rain_btn.grid(row=1, column=2, padx=(0, 10), pady=4)

        # 刷新串口按钮
        refresh_btn = tk.Button(ctrl_inner, text="🔄 刷新串口",
                                font=("Microsoft YaHei", 10),
                                bg=self.CARD_BG, fg=self.ACCENT_BLUE,
                                activebackground="#30363D", activeforeground=self.ACCENT_BLUE,
                                relief=tk.FLAT, cursor="hand2",
                                command=self._refresh_ports)
        refresh_btn.grid(row=1, column=3, padx=(0, 10), pady=4)

        # 开始/结束按钮
        self.start_btn = tk.Button(ctrl_inner, text="▶ 开始采集",
                                   font=("Microsoft YaHei", 11, "bold"),
                                   bg=self.ACCENT_GREEN, fg="#000000",
                                   activebackground="#2EA043", activeforeground="#000000",
                                   relief=tk.FLAT, cursor="hand2", width=12,
                                   command=self._start_collection)
        self.start_btn.grid(row=0, column=5, padx=(0, 8), pady=4)

        self.stop_btn = tk.Button(ctrl_inner, text="⏹ 结束采集",
                                  font=("Microsoft YaHei", 11, "bold"),
                                  bg=self.ACCENT_RED, fg="#FFFFFF",
                                  activebackground="#DA3633", activeforeground="#FFFFFF",
                                  relief=tk.FLAT, cursor="hand2", width=12,
                                  command=self._stop_collection, state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=6, pady=4)

        # ── 数据卡片区域 ──
        self.cards_frame = tk.Frame(main_frame, bg=self.BG_COLOR)
        self.cards_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        # 左：风速传感器卡片
        self._create_wind_card()

        # 中：百叶箱传感器卡片
        self._create_louver_card()

        # 右：雨量传感器卡片
        self._create_rain_card()

        # ── 底栏信息 ──
        footer = tk.Frame(main_frame, bg=self.PANEL_BG,
                          highlightbackground=self.BORDER_COLOR, highlightthickness=1)
        footer.pack(fill=tk.X, pady=(4, 0))
        footer_inner = tk.Frame(footer, bg=self.PANEL_BG)
        footer_inner.pack(fill=tk.X, padx=14, pady=6)

        self.footer_label = tk.Label(footer_inner, text="就绪 — 请选择串口后点击「开始采集」",
                                     font=("Microsoft YaHei", 10),
                                     fg=self.TEXT_SECONDARY, bg=self.PANEL_BG)
        self.footer_label.pack(side=tk.LEFT)

        # 先刷新一次串口
        self._refresh_ports()

    def _create_wind_card(self):
        """风速传感器数据卡片"""
        card = tk.LabelFrame(self.cards_frame, text="   💨 超声波风速风向传感器  ",
                             font=("Microsoft YaHei", 12, "bold"),
                             fg=self.ACCENT_BLUE, bg=self.CARD_BG,
                             foreground=self.ACCENT_BLUE)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        inner = tk.Frame(card, bg=self.CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self.wind_labels: Dict[str, Dict[str, tk.Label]] = {}
        wind_fields = [
            ("瞬时风速", "m/s", "0.00"),
            ("风向角度", "°", "0"),
            ("风向描述", "", "—"),
            ("最大风速", "m/s", "0.00"),
            ("风力等级", "级", "0"),
        ]

        for i, (name, unit, default) in enumerate(wind_fields):
            row_frame = tk.Frame(inner, bg=self.CARD_BG)
            row_frame.pack(fill=tk.X, pady=4)

            tk.Label(row_frame, text=name,
                     font=("Microsoft YaHei", 11),
                     fg=self.TEXT_SECONDARY, bg=self.CARD_BG, width=10, anchor="e"
                     ).pack(side=tk.LEFT, padx=(0, 12))

            val_label = tk.Label(row_frame, text=default,
                                 font=("Consolas", 22, "bold"),
                                 fg=self.TEXT_COLOR, bg=self.CARD_BG, width=10, anchor="e")
            val_label.pack(side=tk.LEFT)

            unit_label = tk.Label(row_frame, text=f" {unit}",
                                  font=("Microsoft YaHei", 11),
                                  fg=self.TEXT_SECONDARY, bg=self.CARD_BG)
            unit_label.pack(side=tk.LEFT)

            self.wind_labels[name] = {"value": val_label, "unit": unit_label}

        # 错误计数
        self.wind_error_label = tk.Label(inner, text="",
                                         font=("Microsoft YaHei", 9),
                                         fg=self.ACCENT_RED, bg=self.CARD_BG)
        self.wind_error_label.pack(pady=(10, 0))

    def _create_louver_card(self):
        """百叶箱传感器数据卡片"""
        card = tk.LabelFrame(self.cards_frame, text="   🌡️ 百叶箱传感器  ",
                             font=("Microsoft YaHei", 12, "bold"),
                             fg=self.ACCENT_YELLOW, bg=self.CARD_BG,
                             foreground=self.ACCENT_YELLOW)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 5))

        inner = tk.Frame(card, bg=self.CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self.louver_labels: Dict[str, Dict[str, tk.Label]] = {}
        louver_fields = [
            ("温度", "°C", "0.0"),
            ("湿度", "%RH", "0.0"),
            ("气压", "kPa", "0.0"),
            ("光照", "Lux", "0.0"),
            ("PM2.5", "µg/m³", "0"),
            ("PM10", "µg/m³", "0"),
            ("噪声", "dB", "0.0"),
            ("CO₂", "ppm", "0"),
            ("TSP", "µg/m³", "0"),
        ]

        for i, (name, unit, default) in enumerate(louver_fields):
            row_frame = tk.Frame(inner, bg=self.CARD_BG)
            row_frame.pack(fill=tk.X, pady=3)

            tk.Label(row_frame, text=name,
                     font=("Microsoft YaHei", 11),
                     fg=self.TEXT_SECONDARY, bg=self.CARD_BG, width=10, anchor="e"
                     ).pack(side=tk.LEFT, padx=(0, 12))

            val_label = tk.Label(row_frame, text=default,
                                 font=("Consolas", 22, "bold"),
                                 fg=self.TEXT_COLOR, bg=self.CARD_BG, width=10, anchor="e")
            val_label.pack(side=tk.LEFT)

            unit_label = tk.Label(row_frame, text=f" {unit}",
                                  font=("Microsoft YaHei", 11),
                                  fg=self.TEXT_SECONDARY, bg=self.CARD_BG)
            unit_label.pack(side=tk.LEFT)

            self.louver_labels[name] = {"value": val_label, "unit": unit_label}

        # 错误计数
        self.louver_error_label = tk.Label(inner, text="",
                                           font=("Microsoft YaHei", 9),
                                           fg=self.ACCENT_RED, bg=self.CARD_BG)
        self.louver_error_label.pack(pady=(10, 0))

    def _create_rain_card(self):
        """雨量传感器数据卡片"""
        card = tk.LabelFrame(self.cards_frame, text="   🌧️ 全不锈钢雨量传感器  ",
                             font=("Microsoft YaHei", 12, "bold"),
                             fg=self.ACCENT_BLUE, bg=self.CARD_BG,
                             foreground=self.ACCENT_BLUE)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))

        inner = tk.Frame(card, bg=self.CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self.rain_labels: Dict[str, Dict[str, tk.Label]] = {}
        rain_fields = [
            ("累计雨量", "mm", "0.0"),
        ]

        for i, (name, unit, default) in enumerate(rain_fields):
            row_frame = tk.Frame(inner, bg=self.CARD_BG)
            row_frame.pack(fill=tk.X, pady=4)

            tk.Label(row_frame, text=name,
                     font=("Microsoft YaHei", 11),
                     fg=self.TEXT_SECONDARY, bg=self.CARD_BG, width=10, anchor="e"
                     ).pack(side=tk.LEFT, padx=(0, 12))

            val_label = tk.Label(row_frame, text=default,
                                 font=("Consolas", 28, "bold"),
                                 fg=self.TEXT_COLOR, bg=self.CARD_BG, width=8, anchor="e")
            val_label.pack(side=tk.LEFT)

            unit_label = tk.Label(row_frame, text=f" {unit}",
                                  font=("Microsoft YaHei", 11),
                                  fg=self.TEXT_SECONDARY, bg=self.CARD_BG)
            unit_label.pack(side=tk.LEFT)

            self.rain_labels[name] = {"value": val_label, "unit": unit_label}

        # 错误计数
        self.rain_error_label = tk.Label(inner, text="",
                                         font=("Microsoft YaHei", 9),
                                         fg=self.ACCENT_RED, bg=self.CARD_BG)
        self.rain_error_label.pack(pady=(10, 0))

        # 清除雨量按钮 (卡片内)
        self.clear_rain_card_btn = tk.Button(inner, text="🧹 清除雨量数据",
                                             font=("Microsoft YaHei", 10, "bold"),
                                             bg=self.ACCENT_ORANGE, fg="#000000",
                                             activebackground="#B55A1E", activeforeground="#000000",
                                             relief=tk.FLAT, cursor="hand2",
                                             command=self._clear_rainfall)
        self.clear_rain_card_btn.pack(pady=(16, 0))

    def _draw_indicator(self, color: str):
        self.status_indicator.delete("all")
        r = 6
        self.status_indicator.create_oval(2, 2, 2 + r * 2, 2 + r * 2,
                                          fill=color, outline=color)

    # ── 事件绑定 ──────────────────────────────────────

    def _bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.running:
            self._stop_collection()
        self.root.destroy()

    # ── 串口刷新 ──────────────────────────────────────

    def _refresh_ports(self):
        """刷新可用串口列表（含"无"选项表示跳过）"""
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []

        # 列表前添加"无"选项
        choices = ["无"] + ports

        current_wind = self.wind_port_var.get()
        current_louver = self.louver_port_var.get()
        current_rain = self.rain_port_var.get()

        self.wind_port_combo['values'] = choices
        self.louver_port_combo['values'] = choices
        self.rain_port_combo['values'] = choices

        if current_wind in choices:
            self.wind_port_var.set(current_wind)
        elif ports:
            self.wind_port_var.set(ports[0])

        if current_louver in choices:
            self.louver_port_var.set(current_louver)
        elif len(ports) > 1:
            self.louver_port_var.set(ports[1])
        elif ports:
            self.louver_port_var.set(ports[0])

        if current_rain in choices:
            self.rain_port_var.set(current_rain)
        elif len(ports) > 2:
            self.rain_port_var.set(ports[2])
        elif ports:
            self.rain_port_var.set(ports[0])

        if not ports:
            self.wind_port_var.set("无")
            self.louver_port_var.set("无")
            self.rain_port_var.set("无")

    # ── 开始/停止采集 ──────────────────────────────────

    def _start_collection(self):
        wind_port = self.wind_port_var.get().strip()
        louver_port = self.louver_port_var.get().strip()
        rain_port = self.rain_port_var.get().strip()

        if not wind_port or not louver_port or not rain_port:
            messagebox.showwarning("串口未设置",
                                   "请先为所有传感器选择串口（无连接请选「无」）！")
            return

        # 至少需要一个非"无"的传感器
        real_ports = [p for p in [wind_port, louver_port, rain_port] if p != "无"]
        if not real_ports:
            messagebox.showwarning("无传感器",
                                   "至少需要连接一个传感器才能开始采集！")
            return

        # 检查非"无"的串口是否有重复
        if len(real_ports) != len(set(real_ports)):
            messagebox.showwarning("串口冲突",
                                   "不同传感器不能使用同一串口！\n"
                                   "当前: 风速={}, 温度={}, 雨量={}".format(wind_port, louver_port, rain_port))
            return

        self.running = True
        self.read_count = 0
        self.wind_error_count = 0
        self.louver_error_count = 0
        self.rain_error_count = 0
        self.last_wind_data = None
        self.last_louver_data = None
        self.last_rain_data = None

        # 记录哪些传感器选择了"无"
        self.wind_skip = (wind_port == "无")
        self.louver_skip = (louver_port == "无")
        self.rain_skip = (rain_port == "无")

        # 启动后台采集线程
        self.data_queue = queue.Queue()
        self.worker = SensorWorker(wind_port, louver_port, rain_port, self.data_queue)
        self.worker.start()

        # 更新UI状态
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.wind_port_combo.config(state=tk.DISABLED)
        self.louver_port_combo.config(state=tk.DISABLED)
        self.rain_port_combo.config(state=tk.DISABLED)
        self._draw_indicator(self.ACCENT_GREEN)
        self.status_label.config(text="采集中", fg=self.ACCENT_GREEN)

        self.footer_label.config(
            text="正在采集 — 风速: {}  |  百叶箱: {}  |  雨量: {} (全部 @9600bps)".format(
                wind_port, louver_port, rain_port))

        # 开始轮询队列
        self._poll_queue()

    def _stop_collection(self):
        self.running = False
        if self.worker:
            self.worker.stop()
            self.worker = None

        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.wind_port_combo.config(state="readonly")
        self.louver_port_combo.config(state="readonly")
        self.rain_port_combo.config(state="readonly")
        self._draw_indicator("gray")
        self.status_label.config(text="已停止", fg=self.TEXT_SECONDARY)

        summary = "已停止 — 共采集 {} 次".format(self.read_count)
        errors = []
        if self.wind_error_count:
            errors.append("风速传感器失败 {} 次".format(self.wind_error_count))
        if self.louver_error_count:
            errors.append("百叶箱传感器失败 {} 次".format(self.louver_error_count))
        if self.rain_error_count:
            errors.append("雨量传感器失败 {} 次".format(self.rain_error_count))
        if errors:
            summary += "  |  " + "  |  ".join(errors)
        self.footer_label.config(text=summary)

    def _poll_queue(self):
        """定期从队列取出数据显示"""
        if not self.running:
            return

        try:
            while True:
                data = self.data_queue.get_nowait()
                self._update_display(data)
        except queue.Empty:
            pass

        # 每 100ms 检查一次队列（比采集频率快）
        self.root.after(100, self._poll_queue)

    # ── 更新显示 ──────────────────────────────────────

    def _update_display(self, data: dict):
        self.read_count = data["counter"]

        wind = data.get("wind")
        louver = data.get("louver")
        rain = data.get("rain")
        wind_skip = data.get("wind_skip", False)
        louver_skip = data.get("louver_skip", False)
        rain_skip = data.get("rain_skip", False)

        # 更新风速传感器卡片
        if wind:
            self.last_wind_data = wind
            self.wind_labels["瞬时风速"]["value"].config(
                text=f"{wind['wind_speed']:.2f}",
                fg=self._wind_speed_color(wind['wind_speed']))
            self.wind_labels["风向角度"]["value"].config(text=f"{wind['wind_dir']:.0f}")
            self.wind_labels["风向描述"]["value"].config(text=wind['wind_dir_text'])
            self.wind_labels["最大风速"]["value"].config(
                text=f"{wind['max_wind_speed']:.2f}")
            self.wind_labels["风力等级"]["value"].config(
                text=f"{wind['wind_level']:.0f}",
                fg=self._wind_level_color(wind['wind_level']))
            self.wind_error_label.config(text="")
        elif wind_skip:
            # "无" — 传感器未连接，不计数错误
            for name in self.wind_labels:
                self.wind_labels[name]["value"].config(text="—", fg=self.TEXT_SECONDARY)
            self.wind_error_label.config(text="未连接", fg=self.TEXT_SECONDARY)
        else:
            self.wind_error_count += 1
            if self.last_wind_data:
                for name in self.wind_labels:
                    self.wind_labels[name]["value"].config(fg=self.ACCENT_ORANGE)
            self.wind_error_label.config(
                text="⚠ 风速传感器读取失败 ({}次)".format(self.wind_error_count))

        # 更新百叶箱传感器卡片
        if louver:
            self.last_louver_data = louver
            self.louver_labels["温度"]["value"].config(
                text=f"{louver['temperature']:.1f}",
                fg=self._temp_color(louver['temperature']))
            self.louver_labels["湿度"]["value"].config(
                text=f"{louver['humidity']:.1f}")
            self.louver_labels["气压"]["value"].config(
                text=f"{louver['pressure']:.1f}")
            self.louver_labels["光照"]["value"].config(
                text=f"{louver['light']:.1f}")
            self.louver_labels["PM2.5"]["value"].config(
                text=f"{louver['pm25']:.0f}",
                fg=self._pm25_color(louver['pm25']))
            self.louver_labels["PM10"]["value"].config(
                text=f"{louver['pm10']:.0f}")
            self.louver_labels["噪声"]["value"].config(
                text=f"{louver['noise']:.1f}")
            self.louver_labels["CO₂"]["value"].config(
                text=f"{louver['co2']:.0f}",
                fg=self._co2_color(louver['co2']))
            self.louver_labels["TSP"]["value"].config(
                text=f"{louver['tsp']:.0f}")
            self.louver_error_label.config(text="")
        elif louver_skip:
            for name in self.louver_labels:
                self.louver_labels[name]["value"].config(text="—", fg=self.TEXT_SECONDARY)
            self.louver_error_label.config(text="未连接", fg=self.TEXT_SECONDARY)
        else:
            self.louver_error_count += 1
            if self.last_louver_data:
                for name in self.louver_labels:
                    self.louver_labels[name]["value"].config(fg=self.ACCENT_ORANGE)
            self.louver_error_label.config(
                text="⚠ 百叶箱传感器读取失败 ({}次)".format(self.louver_error_count))

        # 更新雨量传感器卡片
        if rain:
            self.last_rain_data = rain
            self.rain_labels["累计雨量"]["value"].config(
                text="{:.1f}".format(rain['rainfall']),
                fg=self._rain_color(rain['rainfall']))
            self.rain_error_label.config(text="")
        elif rain_skip:
            self.rain_labels["累计雨量"]["value"].config(text="—", fg=self.TEXT_SECONDARY)
            self.rain_error_label.config(text="未连接", fg=self.TEXT_SECONDARY)
        else:
            self.rain_error_count += 1
            if self.last_rain_data:
                for name in self.rain_labels:
                    self.rain_labels[name]["value"].config(fg=self.ACCENT_ORANGE)
            self.rain_error_label.config(
                text="⚠ 雨量传感器读取失败 ({}次)".format(self.rain_error_count))

        # 更新底栏时间
        ts = data["timestamp"]
        status = "第 {} 次采集  |  {}".format(self.read_count, ts)
        # 统计实际连接的传感器
        connected = sum([1 for x in [wind_skip, louver_skip, rain_skip] if not x])
        ok_count = sum([1 for x in [wind, louver, rain] if x])
        if connected == 0:
            status += "  ⚠ 无传感器连接"
        elif ok_count == connected:
            status += "  ✅ {}个传感器正常".format(connected)
        elif ok_count > 0:
            status += "  ⚠ {}/{}个传感器正常".format(ok_count, connected)
        else:
            status += "  ❌ {}个传感器全部异常".format(connected)
        self.footer_label.config(text=status)

    # ── 颜色辅助 ──────────────────────────────────────

    @staticmethod
    def _wind_speed_color(speed: float) -> str:
        if speed < 3:
            return "#E6EDF3"
        elif speed < 8:
            return "#D29922"
        else:
            return "#F85149"

    @staticmethod
    def _wind_level_color(level: int) -> str:
        if level <= 2:
            return "#E6EDF3"
        elif level <= 5:
            return "#D29922"
        else:
            return "#F85149"

    @staticmethod
    def _temp_color(temp: float) -> str:
        if temp < -10:
            return "#58A6FF"
        elif temp > 35:
            return "#F85149"
        else:
            return "#E6EDF3"

    @staticmethod
    def _pm25_color(pm25: int) -> str:
        if pm25 <= 35:
            return "#3FB950"
        elif pm25 <= 75:
            return "#D29922"
        else:
            return "#F85149"

    @staticmethod
    def _co2_color(co2: int) -> str:
        if co2 <= 800:
            return "#3FB950"
        elif co2 <= 1500:
            return "#D29922"
        else:
            return "#F85149"

    @staticmethod
    def _rain_color(rainfall: float) -> str:
        if rainfall <= 0:
            return "#E6EDF3"
        elif rainfall < 10:
            return "#58A6FF"
        elif rainfall < 25:
            return "#D29922"
        else:
            return "#F85149"

    # ── 清除雨量 ──────────────────────────────────────

    def _clear_rainfall(self):
        """清除雨量计数器数据"""
        rain_port = self.rain_port_var.get().strip()
        if not rain_port:
            messagebox.showwarning("串口未设置", "请先选择雨量传感器串口！")
            return

        confirm = messagebox.askyesno(
            "确认清除",
            "确定要清除雨量计数据吗？\n(向寄存器 0x0000 写入 0x005A)")
        if not confirm:
            return

        success = clear_rain_data(rain_port, dev_addr=0x01, baud=9600)
        if success:
            messagebox.showinfo("成功", "雨量数据已清除！")
            # 立即更新显示为 0
            if hasattr(self, 'rain_labels'):
                self.rain_labels["累计雨量"]["value"].config(text="0.0", fg="#E6EDF3")
            self.last_rain_data = {"rainfall": 0.0}
        else:
            messagebox.showerror("失败", "清除雨量数据失败，请检查串口连接。")

    # ── 启动 ──────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# ======================================================
#  入口
# ======================================================

if __name__ == "__main__":
    app = SensorDisplayApp()
    app.run()
