#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  RID900 无人机探测模块 — 独立实时监控界面
=============================================================================
  功能:
    1.  自动检测并连接串口 (115200, 8N1)
    2.  实时显示模块心跳信息 ($HBRID) — 设备 ID / GPS / 信号.
    3.  多目标无人机列表 — 按信号强度排序, 支持点击切换
    4.  单目标详情面板 — 完整 RID 信息 (身份 / 位置 / 速度 / 姿态 / 飞手)
    5.  原始数据日志滚动显示
    6.  支持热插拔检测
    7.  暗色专业主题

  依赖:  pyserial, tkinter (内置)

  用法:
    python rid_gui_monitor.py

  协议:
    串口参数: 115200, 8N1, 无流控
    报文格式: $HBRID (心跳) / $GBRID (无人机探测)
=============================================================================
"""

import sys
import time
import json
import threading
import queue
from datetime import datetime
from typing import Optional, List, Dict
from collections import deque

# ── 本地解析模块 ──
try:
    from rid_module import (
        RIDParser, RIDSerialReader, DroneTracker,
        HeartbeatInfo, DroneInfo
    )
except ImportError:
    print("[错误] 找不到 rid_module.py，请确保在同一目录下。")
    sys.exit(1)

# ── 串口库 ──
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[错误] 请先安装 pyserial →  pip install pyserial")
    sys.exit(1)

# ── GUI 库 ──
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:
    print("[错误] Tkinter 不可用，请安装 python3-tk")
    sys.exit(1)


# =============================================================================
#  全局配置
# =============================================================================

DEFAULT_BAUDRATE = 115200          # RID900 固定波特率
DEFAULT_TIMEOUT  = 2.0
STALE_TIMEOUT    = 60.0            # 目标超时淘汰 (秒)
AUTO_SCAN_MS     = 3000            # 串口自动扫描间隔 (毫秒)
GUI_REFRESH_MS   = 50              # GUI 刷新间隔 (毫秒)


# =============================================================================
#  颜色主题 — 暗色专业风格
# =============================================================================

class Theme:
    BG_DARK      = "#0d1117"
    BG_PANEL     = "#161b22"
    BG_CARD      = "#21262d"
    BG_HEADER    = "#1a1f2e"
    BG_TABLE_ALT = "#1c2128"
    FG_PRIMARY   = "#e6edf3"
    FG_SECONDARY = "#8b949e"
    FG_ACCENT    = "#58a6ff"
    FG_GREEN     = "#3fb950"
    FG_YELLOW    = "#d29922"
    FG_RED       = "#ff4d4d"
    FG_ORANGE    = "#ff8c00"
    FG_PURPLE    = "#bc8cff"
    BORDER       = "#30363d"
    FONT_TITLE   = ("Microsoft YaHei UI", 14, "bold")
    FONT_SUBTITLE = ("Microsoft YaHei UI", 11, "bold")
    FONT_BODY    = ("Microsoft YaHei UI", 10)
    FONT_MONO    = ("Consolas", 10)
    FONT_BIG     = ("Consolas", 22, "bold")
    FONT_GAUGE   = ("Consolas", 28, "bold")
    FONT_SMALL   = ("Microsoft YaHei UI", 9)
    FONT_TABLE   = ("Microsoft YaHei UI", 10)


# =============================================================================
#  主 GUI 界面
# =============================================================================

class RIDMonitorApp:
    """RID900 无人机探测 — 独立监控界面"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RID900 无人机探测 — 实时监控")
        self.root.geometry("1400x880")
        self.root.minsize(1200, 750)
        self.root.configure(bg=Theme.BG_DARK)

        # ── 状态变量 ──
        self.reader: Optional[RIDSerialReader] = None
        self.result_queue: queue.Queue = queue.Queue()
        self.tracker = DroneTracker(timeout=STALE_TIMEOUT)

        self.heartbeat: HeartbeatInfo = HeartbeatInfo()
        self.selected_serial: str = ""          # 当前选中的无人机序列号
        self.is_connected = False
        self.update_count = 0
        self.total_drones_seen = 0
        self.fps_history: deque = deque(maxlen=30)
        self.hbrid_count = 0
        self.gbrid_count = 0

        # ── Widget 引用 ──
        self.port_var: tk.StringVar = None
        self.port_combo: ttk.Combobox = None
        self.connect_btn: tk.Button = None
        self.connection_indicator: tk.Canvas = None
        self.detect_indicator: tk.Label = None
        self.status_bar_label: tk.Label = None
        self.status_bar_right: tk.Label = None

        # 心跳面板
        self.hb_labels: Dict[str, tk.Label] = {}
        self.hb_mode_label: tk.Label = None          # 心跳模式提示
        # 无人机列表 (Treeview)
        self.drone_tree: ttk.Treeview = None
        self.drone_empty_label: tk.Label = None      # 空列表占位提示
        # 详情面板
        self.detail_labels: Dict[str, tk.Label] = {}
        self.detail_placeholder: tk.Label = None     # 无选中占位提示
        # 日志
        self.log_text: scrolledtext.ScrolledText = None

        # ── 构建界面 ──
        self._build_ui()
        self._refresh_port_list()

        # ── 启动事件循环 ──
        self._process_queue()
        self._auto_scan_ports()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    #  UI 构建
    # =========================================================================

    def _build_ui(self):
        self._build_header()
        self._build_main_area()
        self._build_status_bar()

    def _build_header(self):
        """顶部标题栏 — 连接控制"""
        header = tk.Frame(self.root, bg=Theme.BG_HEADER, height=56)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        # 标题
        tk.Label(
            header, text="🛰  RID900 无人机探测模块 — 实时监控系统",
            font=Theme.FONT_TITLE, bg=Theme.BG_HEADER, fg=Theme.FG_PRIMARY
        ).pack(side=tk.LEFT, padx=(16, 8), pady=14)

        # 串口选择
        tk.Label(header, text="串口:", font=Theme.FONT_BODY,
                 bg=Theme.BG_HEADER, fg=Theme.FG_SECONDARY
                 ).pack(side=tk.LEFT, padx=(8, 3), pady=14)

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            header, textvariable=self.port_var, state="readonly",
            font=Theme.FONT_BODY, width=12
        )
        self.port_combo.pack(side=tk.LEFT, padx=2, pady=14)

        tk.Button(
            header, text="🔄", font=Theme.FONT_BODY,
            bg=Theme.BG_CARD, fg=Theme.FG_PRIMARY,
            activebackground=Theme.BORDER, activeforeground=Theme.FG_ACCENT,
            relief=tk.FLAT, cursor="hand2", padx=8,
            command=self._refresh_port_list
        ).pack(side=tk.LEFT, padx=(2, 8), pady=12)

        # 连接按钮
        self.connect_btn = tk.Button(
            header, text="⚡ 连接", font=Theme.FONT_SUBTITLE,
            bg=Theme.FG_GREEN, fg="#000000",
            activebackground="#2ea043", activeforeground="#000000",
            relief=tk.FLAT, cursor="hand2", padx=18, pady=2,
            command=self._toggle_connection
        )
        self.connect_btn.pack(side=tk.LEFT, padx=6, pady=12)

        # 连接状态指示灯
        self.connection_indicator = tk.Canvas(
            header, width=16, height=16, bg=Theme.BG_HEADER, highlightthickness=0
        )
        self.connection_indicator.pack(side=tk.LEFT, padx=2, pady=14)
        self._draw_indicator("gray")

        # 无人机探测状态指示
        self.detect_indicator = tk.Label(
            header, text="🔍 等待无人机信号...",
            font=("Microsoft YaHei UI", 10, "bold"),
            bg=Theme.BG_HEADER, fg=Theme.FG_YELLOW
        )
        self.detect_indicator.pack(side=tk.LEFT, padx=(12, 4), pady=14)

        # 时钟
        self.clock_label = tk.Label(
            header, text="", font=Theme.FONT_MONO,
            bg=Theme.BG_HEADER, fg=Theme.FG_SECONDARY
        )
        self.clock_label.pack(side=tk.RIGHT, padx=16, pady=14)

    def _build_main_area(self):
        """主体区域: 左侧心跳+详情, 右侧无人机列表+日志"""
        main = tk.Frame(self.root, bg=Theme.BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        # ── 左侧面板 (固定宽度) ──
        left_frame = tk.Frame(main, bg=Theme.BG_DARK, width=580)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left_frame.pack_propagate(False)

        self._build_heartbeat_panel(left_frame)
        self._build_detail_panel(left_frame)

        # ── 右侧面板 (弹性) ──
        right_frame = tk.Frame(main, bg=Theme.BG_DARK)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

        self._build_drone_list_panel(right_frame)
        self._build_log_panel(right_frame)

    # =========================================================================
    #  左侧 — 模块心跳面板
    # =========================================================================

    def _build_heartbeat_panel(self, parent: tk.Frame):
        """模块自身状态 — 心跳信息 (未检测到无人机时仅上报此报文)"""
        frame = tk.LabelFrame(
            parent, text="📡  模块自检心跳 ($HBRID) — 设备自身状态报文",
            font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            foreground=Theme.FG_ACCENT, padx=10, pady=6
        )
        frame.pack(fill=tk.X, pady=(0, 6))

        # 模式提示条
        mode_bar = tk.Frame(frame, bg=Theme.BG_CARD, padx=6, pady=3)
        mode_bar.pack(fill=tk.X, pady=(0, 4))
        self.hb_mode_label = tk.Label(
            mode_bar, text="🔍 当前模式: 仅心跳 — 等待无人机起飞...",
            font=Theme.FONT_SMALL, bg=Theme.BG_CARD, fg=Theme.FG_YELLOW
        )
        self.hb_mode_label.pack(anchor=tk.W)

        # 设备 ID
        id_row = tk.Frame(frame, bg=Theme.BG_PANEL)
        id_row.pack(fill=tk.X, pady=1)
        tk.Label(id_row, text="设备 ID:", font=Theme.FONT_BODY,
                 bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY, width=12, anchor=tk.W
                 ).pack(side=tk.LEFT)
        self.hb_labels["device_id"] = tk.Label(
            id_row, text="--", font=("Consolas", 16, "bold"),
            bg=Theme.BG_PANEL, fg=Theme.FG_ACCENT
        )
        self.hb_labels["device_id"].pack(side=tk.LEFT, padx=6)
        self.hb_labels["hb_time"] = tk.Label(
            id_row, text="", font=Theme.FONT_SMALL,
            bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY
        )
        self.hb_labels["hb_time"].pack(side=tk.RIGHT, padx=4)

        # 分隔线
        tk.Frame(frame, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=4)

        # GPS 信息 (2x2)
        gps_frame = tk.Frame(frame, bg=Theme.BG_PANEL)
        gps_frame.pack(fill=tk.X, pady=2)
        for i, (label, key) in enumerate([
            ("设备经度", "dev_lon"), ("设备纬度", "dev_lat"),
            ("设备海拔(m)", "dev_alt"), ("状态码", "dev_status"),
        ]):
            row = i // 2
            col = i % 2
            card = tk.Frame(gps_frame, bg=Theme.BG_CARD, padx=8, pady=4,
                            highlightbackground=Theme.BORDER, highlightthickness=1)
            card.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
            gps_frame.grid_columnconfigure(col, weight=1)

            tk.Label(card, text=label, font=Theme.FONT_SMALL,
                     bg=Theme.BG_CARD, fg=Theme.FG_SECONDARY).pack(anchor=tk.W)
            lbl = tk.Label(card, text="--", font=("Consolas", 13, "bold"),
                           bg=Theme.BG_CARD, fg=Theme.FG_ACCENT)
            lbl.pack(anchor=tk.W, pady=(1, 0))
            self.hb_labels[key] = lbl

        # 信号 (RSSI / SNR)
        sig_frame = tk.Frame(frame, bg=Theme.BG_PANEL)
        sig_frame.pack(fill=tk.X, pady=2)
        for i, (label, key) in enumerate([
            ("设备 RSSI", "dev_rssi"), ("设备 SNR", "dev_snr"),
        ]):
            card = tk.Frame(sig_frame, bg=Theme.BG_CARD, padx=8, pady=4,
                            highlightbackground=Theme.BORDER, highlightthickness=1)
            card.grid(row=0, column=i, padx=3, pady=3, sticky="nsew")
            sig_frame.grid_columnconfigure(i, weight=1)

            tk.Label(card, text=label, font=Theme.FONT_SMALL,
                     bg=Theme.BG_CARD, fg=Theme.FG_SECONDARY).pack(anchor=tk.W)
            lbl = tk.Label(card, text="--", font=("Consolas", 13, "bold"),
                           bg=Theme.BG_CARD, fg=Theme.FG_ACCENT)
            lbl.pack(anchor=tk.W, pady=(1, 0))
            self.hb_labels[key] = lbl

    # =========================================================================
    #  左侧 — 当前选中无人机详情 (可滚动)
    # =========================================================================

    def _build_detail_panel(self, parent: tk.Frame):
        """选中无人机完整详情 — 内容溢出时支持垂直滚动"""
        frame = tk.LabelFrame(
            parent, text="🔍  目标详情 ($GBRID)", font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            foreground=Theme.FG_PURPLE, padx=2, pady=4
        )
        frame.pack(fill=tk.BOTH, expand=True)

        # ── Canvas + Scrollbar 实现滚动 ──
        canvas = tk.Canvas(frame, bg=Theme.BG_PANEL, highlightthickness=0,
                           bd=0, relief=tk.FLAT)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        # 可滚动内容框架
        inner = tk.Frame(canvas, bg=Theme.BG_PANEL, padx=8)
        inner_window = canvas.create_window((0, 0), window=inner,
                                            anchor=tk.NW, tags=("inner",))

        # 动态更新 scrollregion
        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        # 同步 inner 宽度到 canvas 宽度
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # 鼠标滚轮滚动 (仅在鼠标悬停时生效)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_wheel(e):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_wheel(e):
            canvas.unbind_all("<MouseWheel>")
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        # 支持触控板双指滚动 (Linux/Wayland)
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 无选中占位提示 (覆盖在外层 frame 上，不随内容滚动)
        self.detail_placeholder = tk.Label(
            frame, text="👈 请在右侧目标列表中\n点击选择一个无人机查看详情",
            font=("Microsoft YaHei UI", 12), bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY,
            justify=tk.CENTER
        )
        self.detail_placeholder.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # ── 以下所有内容放入可滚动 inner 框架 ──

        # 身份信息
        self._detail_section(inner, "🆔  身份信息", [
            ("序列号", "serial"), ("厂商", "vendor"), ("型号", "model"),
        ], cols=1)

        tk.Frame(inner, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=3)

        # 位置信息 (2x3)
        self._detail_section(inner, "📍  位置信息", [
            ("无人机经度", "d_lon"), ("无人机纬度", "d_lat"),
            ("离地高度(m)", "height"), ("海拔高度(m)", "alt"),
            ("气压高度(m)", "pressure"),
        ], cols=2)

        tk.Frame(inner, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=3)

        # 飞行数据 (2x3)
        self._detail_section(inner, "🧭  飞行数据", [
            ("航向角(°)", "yaw"), ("水平速度(m/s)", "east_speed"),
            ("垂直速度(m/s)", "up_speed"),
        ], cols=2)

        tk.Frame(inner, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=3)

        # 信号质量 (1x3)
        self._detail_section(inner, "📶  信号质量", [
            ("RSSI(dBm)", "rssi"), ("SNR(dB)", "snr"),
        ], cols=2)

        tk.Frame(inner, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=3)

        # 飞手信息 (2x3)
        self._detail_section(inner, "🎮  飞手位置", [
            ("飞手经度", "p_lon"), ("飞手纬度", "p_lat"),
            ("飞手海拔(m)", "p_height"),
        ], cols=2)

        # 设备属性
        tk.Frame(inner, bg=Theme.BORDER, height=1).pack(fill=tk.X, pady=3)
        self._detail_section(inner, "⚙  设备属性", [
            ("设备类型", "drone_type"), ("设备种类", "drone_class"),
            ("状态信息", "state_info"), ("位置误差(m)", "pos_err"),
            ("高度误差(m)", "height_err"),
        ], cols=2)

    def _detail_section(self, parent: tk.Frame, title: str,
                        items: List[tuple], cols: int = 1):
        """创建详情区块"""
        container = tk.Frame(parent, bg=Theme.BG_PANEL)
        container.pack(fill=tk.X, padx=2, pady=2)

        tk.Label(container, text=title, font=Theme.FONT_SMALL,
                 bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY
                 ).pack(anchor=tk.W, pady=(2, 0))

        grid = tk.Frame(container, bg=Theme.BG_PANEL)
        grid.pack(fill=tk.X, pady=1)

        for i, (label, key) in enumerate(items):
            row = i // cols
            col = i % cols
            card = tk.Frame(grid, bg=Theme.BG_CARD, padx=6, pady=2,
                            highlightbackground=Theme.BORDER, highlightthickness=1)
            card.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
            for c in range(cols):
                grid.grid_columnconfigure(c, weight=1)

            tk.Label(card, text=label, font=Theme.FONT_SMALL,
                     bg=Theme.BG_CARD, fg=Theme.FG_SECONDARY).pack(anchor=tk.W)
            lbl = tk.Label(card, text="--", font=("Consolas", 11, "bold"),
                           bg=Theme.BG_CARD, fg=Theme.FG_ACCENT)
            lbl.pack(anchor=tk.W)
            self.detail_labels[key] = lbl

    # =========================================================================
    #  右侧 — 无人机目标列表
    # =========================================================================

    def _build_drone_list_panel(self, parent: tk.Frame):
        """多目标无人机列表 (Treeview)"""
        frame = tk.LabelFrame(
            parent, text="🎯  探测目标列表", font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            foreground=Theme.FG_GREEN, padx=6, pady=4
        )
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        # 工具栏: 统计 + 搜索
        toolbar = tk.Frame(frame, bg=Theme.BG_PANEL)
        toolbar.pack(fill=tk.X, pady=(0, 4))

        self.target_count_label = tk.Label(
            toolbar, text="在线目标: 0", font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_GREEN
        )
        self.target_count_label.pack(side=tk.LEFT, padx=2)

        self.total_seen_label = tk.Label(
            toolbar, text="累计发现: 0", font=Theme.FONT_SMALL,
            bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY
        )
        self.total_seen_label.pack(side=tk.LEFT, padx=8)

        self.gbrid_count_label = tk.Label(
            toolbar, text="报文: 0", font=Theme.FONT_SMALL,
            bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY
        )
        self.gbrid_count_label.pack(side=tk.RIGHT, padx=2)

        # 排序选择
        tk.Label(toolbar, text="排序:", font=Theme.FONT_SMALL,
                 bg=Theme.BG_PANEL, fg=Theme.FG_SECONDARY).pack(side=tk.RIGHT, padx=(8, 2))
        self.sort_var = tk.StringVar(value="信号强度↓")
        sort_cb = ttk.Combobox(
            toolbar, textvariable=self.sort_var, state="readonly",
            font=Theme.FONT_SMALL, width=10,
            values=["信号强度↓", "信号强度↑", "水平速度↓", "最近更新↓"]
        )
        sort_cb.pack(side=tk.RIGHT, padx=2)
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_drone_list())

        # Treeview 表格
        tree_container = tk.Frame(frame, bg=Theme.BG_PANEL)
        tree_container.pack(fill=tk.BOTH, expand=True)

        columns = ("serial", "vendor_model", "rssi", "snr",
                    "lon", "lat", "height", "yaw", "speed", "up_speed")
        self.drone_tree = ttk.Treeview(
            tree_container, columns=columns, show="headings",
            height=14, selectmode="browse"
        )

        # 列定义
        col_defs = [
            ("serial",       "序列号",        150),
            ("vendor_model", "厂商/型号",     160),
            ("rssi",         "RSSI(dBm)",     80),
            ("snr",          "SNR(dB)",       65),
            ("lon",          "经度",           100),
            ("lat",          "纬度",           100),
            ("height",       "离地高(m)",      80),
            ("yaw",          "航向(°)",       70),
            ("speed",        "水平(m/s)",      80),
            ("up_speed",     "垂直(m/s)",      80),
        ]
        for col_id, col_name, width in col_defs:
            self.drone_tree.heading(col_id, text=col_name)
            self.drone_tree.column(col_id, width=width, anchor=tk.CENTER,
                                   minwidth=50)

        # 滚动条
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL,
                                     command=self.drone_tree.yview)
        self.drone_tree.configure(yscrollcommand=tree_scroll.set)

        self.drone_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 空列表占位提示 (覆盖在 Treeview 上方)
        self.drone_empty_label = tk.Label(
            tree_container, text="暂无探测目标\n设备正在扫描中，请等待无人机起飞...",
            font=("Microsoft YaHei UI", 13), bg=Theme.BG_CARD, fg=Theme.FG_SECONDARY,
            justify=tk.CENTER
        )

        # 样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=Theme.BG_CARD,
                        foreground=Theme.FG_PRIMARY,
                        fieldbackground=Theme.BG_CARD,
                        borderwidth=0,
                        font=Theme.FONT_TABLE,
                        rowheight=26)
        style.configure("Treeview.Heading",
                        background=Theme.BG_HEADER,
                        foreground=Theme.FG_ACCENT,
                        font=("Microsoft YaHei UI", 9, "bold"),
                        borderwidth=0)
        style.map("Treeview",
                  background=[("selected", Theme.FG_ACCENT)],
                  foreground=[("selected", "#000000")])

        # 点击事件 — 选中目标查看详情
        self.drone_tree.bind("<<TreeviewSelect>>", self._on_drone_selected)

    # =========================================================================
    #  右侧 — 原始数据日志
    # =========================================================================

    def _build_log_panel(self, parent: tk.Frame):
        """原始报文日志"""
        frame = tk.LabelFrame(
            parent, text="📋  原始数据日志", font=Theme.FONT_SUBTITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            foreground=Theme.FG_SECONDARY, padx=6, pady=4
        )
        frame.pack(fill=tk.X, pady=(0, 0))

        self.log_text = scrolledtext.ScrolledText(
            frame, height=8, font=("Consolas", 9),
            bg=Theme.BG_CARD, fg=Theme.FG_SECONDARY,
            insertbackground=Theme.FG_PRIMARY,
            relief=tk.FLAT, borderwidth=0,
            state=tk.DISABLED, wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

    # =========================================================================
    #  底部状态栏
    # =========================================================================

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=Theme.BG_HEADER, height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        self.status_bar_label = tk.Label(
            bar, text="未连接  |  模式: --", font=("Microsoft YaHei UI", 9),
            bg=Theme.BG_HEADER, fg=Theme.FG_SECONDARY, anchor=tk.W
        )
        self.status_bar_label.pack(side=tk.LEFT, fill=tk.X, padx=12, pady=3)

        self.status_bar_right = tk.Label(
            bar, text="更新: 0 | 刷新: -- Hz",
            font=("Microsoft YaHei UI", 9),
            bg=Theme.BG_HEADER, fg=Theme.FG_SECONDARY
        )
        self.status_bar_right.pack(side=tk.RIGHT, padx=12, pady=3)

    def _draw_indicator(self, color: str):
        self.connection_indicator.delete("all")
        self.connection_indicator.create_oval(2, 2, 14, 14, fill=color, outline="")

    # =========================================================================
    #  串口管理
    # =========================================================================

    def _refresh_port_list(self):
        try:
            ports = list(serial.tools.list_ports.comports())
            port_names = [p.device for p in ports]
        except Exception:
            port_names = []

        port_names = ["无"] + port_names
        self.port_combo["values"] = port_names
        if port_names and not self.port_var.get():
            self.port_var.set(port_names[0])
        if not port_names:
            self.port_var.set("无")

    def _auto_scan_ports(self):
        if not self.is_connected:
            current = self.port_var.get()
            self._refresh_port_list()
            if current and current in self.port_combo["values"]:
                self.port_var.set(current)
        self.root.after(AUTO_SCAN_MS, self._auto_scan_ports)

    def _toggle_connection(self):
        if self.is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self.port_var.get().strip()
        if not port or port == "无":
            messagebox.showwarning("警告", "请先选择串口，或选择「无」跳过。")
            return

        self.reader = RIDSerialReader(port, DEFAULT_BAUDRATE, self.result_queue)
        self.reader.start()

        self.gbrid_count = 0
        self.hbrid_count = 0
        self._set_detect_mode(False)
        self.connect_btn.config(text="⏹ 断开", bg=Theme.FG_RED,
                                activebackground="#cc3333")
        self.status_bar_label.config(
            text=f"正在连接 {port} @ {DEFAULT_BAUDRATE} bps...")
        self._log(f"[系统] 正在连接 {port} @ {DEFAULT_BAUDRATE} bps (8N1)...")

    def _disconnect(self):
        if self.reader:
            self.reader.stop()
            self.reader = None

        self.is_connected = False
        self._draw_indicator("gray")
        self.gbrid_count = 0
        self.hbrid_count = 0
        self._set_detect_mode(False)
        self.connect_btn.config(text="⚡ 连接", bg=Theme.FG_GREEN,
                                activebackground="#2ea043")
        self.status_bar_label.config(text="已断开")
        self._log("[系统] 已断开连接。")

        # 清空显示
        self.tracker.clear()
        self._refresh_drone_list()
        self._clear_heartbeat()
        self._clear_detail()

    # =========================================================================
    #  消息处理循环
    # =========================================================================

    def _process_queue(self):
        """定时在 GUI 线程中处理来自串口的消息"""
        try:
            while True:
                msg = self.result_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "STATUS":
                    self._handle_status(msg)
                elif msg_type == "HBRID":
                    self._handle_hbrid(msg[1])
                elif msg_type == "GBRID":
                    self._handle_gbrid(msg[1])

        except queue.Empty:
            pass

        # 更新超时目标
        self.tracker.remove_stale()

        # 计算 FPS
        now = time.time()
        self.fps_history.append(now)
        if len(self.fps_history) >= 2:
            dt = self.fps_history[-1] - self.fps_history[0]
            fps = (len(self.fps_history) - 1) / dt if dt > 0 else 0
        else:
            fps = 0

        # 更新时钟
        self.clock_label.config(text=f"⏱ {datetime.now().strftime('%H:%M:%S')}")

        # 更新状态栏
        detect_state = "探测中" if self.gbrid_count > 0 else "仅心跳"
        self.status_bar_right.config(
            text=f"更新: {self.update_count} | 刷新: {fps:.1f} Hz  |  "
                 f"状态: {detect_state}  |  "
                 f"HBRID: {self.hbrid_count}  GBRID: {self.gbrid_count}")

        self.root.after(GUI_REFRESH_MS, self._process_queue)

    def _handle_status(self, msg):
        _, status, detail, *rest = msg
        if status == "connected":
            self.is_connected = True
            self._draw_indicator(Theme.FG_GREEN)
            baud = rest[0] if rest else DEFAULT_BAUDRATE
            self.status_bar_label.config(
                text=f"已连接: {detail} @ {baud} bps  |  模式: 仅心跳")
            self._log(f"[系统] ✓ 连接成功: {detail} @ {baud} bps (8N1)")
        elif status == "reconnected":
            # USB 复位后重连成功
            self.is_connected = True
            self._draw_indicator(Theme.FG_GREEN)
            baud = rest[0] if rest else DEFAULT_BAUDRATE
            self.status_bar_label.config(
                text=f"已重连: {detail} @ {baud} bps  |  模式: 仅心跳")
            self._log(f"[系统] ✓ USB 复位后重连成功: {detail} @ {baud} bps")
        elif status == "nodata":
            # 连接后无数据 — 正在自动 USB 复位重试
            self._log(f"[警告] ⚠ {detail}")
            self.status_bar_label.config(text=detail)
        elif status == "nodata_max":
            # USB 复位耗尽 — 提示用户手动插拔
            self._log(f"[错误] ❌ {detail}")
            self.status_bar_label.config(text="无数据, 请手动插拔 RID 设备")
            if self.reader:
                self.reader.stop()
                self.reader = None
            self.is_connected = False
            self._draw_indicator("gray")
            self.connect_btn.config(text="⚡ 连接", bg=Theme.FG_GREEN,
                                    activebackground="#2ea043")
            messagebox.showwarning(
                "无数据",
                f"已连接 {DEFAULT_BAUDRATE} bps 但 {self.reader.port if self.reader else self.port_var.get()} "
                f"无任何报文。\n\n请手动插拔 RID 设备后再点击「连接」。")
        elif status == "disconnected":
            self.is_connected = False
            self._disconnect()
            self._log(f"[系统] ✗ 连接断开: {detail}")
        elif status == "error":
            self._log(f"[错误] {detail}")
            self.status_bar_label.config(text=f"错误: {detail}")
            if not self.is_connected and self.reader:
                self._disconnect()

    def _handle_hbrid(self, hb: HeartbeatInfo):
        """更新模块心跳信息"""
        self.heartbeat = hb
        self.hbrid_count += 1
        self.update_count += 1

        self.hb_labels["device_id"].config(text=hb.device_id)
        self.hb_labels["dev_lon"].config(text=f"{hb.longitude:.6f}")
        self.hb_labels["dev_lat"].config(text=f"{hb.latitude:.6f}")
        self.hb_labels["dev_alt"].config(text=f"{hb.altitude:.2f}")
        self.hb_labels["dev_status"].config(text=str(hb.status))
        self.hb_labels["dev_rssi"].config(
            text=f"{hb.rssi} dBm", fg=self._rssi_color(hb.rssi))
        self.hb_labels["dev_snr"].config(
            text=f"{hb.snr} dB", fg=self._snr_color(hb.snr))
        self.hb_labels["hb_time"].config(
            text=datetime.fromtimestamp(hb.timestamp).strftime("%H:%M:%S.%f")[:-4])

        # 若还未检测到无人机，维持"仅心跳"模式提示
        if self.gbrid_count == 0:
            self._set_detect_mode(False)

    def _handle_gbrid(self, drone: DroneInfo):
        """处理无人机探测报文"""
        if not drone.is_valid:
            return

        self.gbrid_count += 1
        self.update_count += 1

        # 首次检测到无人机 — 切换探测模式
        if self.gbrid_count == 1:
            self._set_detect_mode(True)

        is_new = self.tracker.update(drone)
        if is_new:
            self.total_drones_seen += 1
            self._log(f"[发现] 新目标: {drone.drone_serial_num}  "
                      f"{drone.vendor_str} {drone.product_type_str}  "
                      f"RSSI={drone.detect_rssi} dBm")

        # 刷新列表
        self._refresh_drone_list()

        # 如果当前选中的目标有更新, 刷新详情
        if self.selected_serial:
            updated = self.tracker.get(self.selected_serial)
            if updated:
                self._update_detail(updated)

    # =========================================================================
    #  探测模式切换
    # =========================================================================

    def _set_detect_mode(self, detected: bool):
        """切换界面模式: 仅心跳 / 探测中"""
        if detected:
            self.detect_indicator.config(
                text="🛸 已检测到无人机!", fg=Theme.FG_GREEN)
            self.hb_mode_label.config(
                text="🛸 当前模式: $HBRID心跳 + $GBRID探测 — 无人机已起飞",
                fg=Theme.FG_GREEN)
            if self.is_connected:
                self.status_bar_label.config(
                    text=f"已连接: {self.reader.port if self.reader else '?'} @ "
                         f"{DEFAULT_BAUDRATE} bps  |  模式: 探测中 🛸")
        else:
            self.detect_indicator.config(
                text="🔍 等待无人机信号...", fg=Theme.FG_YELLOW)
            self.hb_mode_label.config(
                text="🔍 当前模式: 仅心跳 — 等待无人机起飞...",
                fg=Theme.FG_YELLOW)
            if self.is_connected:
                self.status_bar_label.config(
                    text=f"已连接: {self.reader.port if self.reader else '?'} @ "
                         f"{DEFAULT_BAUDRATE} bps  |  模式: 仅心跳")

    # =========================================================================
    #  无人机列表刷新
    # =========================================================================

    def _refresh_drone_list(self):
        """刷新 Treeview"""
        # 保存选中
        sel_items = self.drone_tree.selection()
        sel_serial = None
        if sel_items:
            sel_serial = self.drone_tree.item(sel_items[0], "values")[0]

        # 清空
        for item in self.drone_tree.get_children():
            self.drone_tree.delete(item)

        # 排序
        sort_by = self.sort_var.get()
        if sort_by == "信号强度↓":
            drones = self.tracker.get_sorted('rssi', reverse=True)
        elif sort_by == "信号强度↑":
            drones = self.tracker.get_sorted('rssi', reverse=False)
        elif sort_by == "水平速度↓":
            drones = self.tracker.get_sorted('speed', reverse=True)
        elif sort_by == "最近更新↓":
            drones = self.tracker.get_sorted('time', reverse=True)
        else:
            drones = self.tracker.get_sorted('rssi', reverse=True)

        # 空列表 — 显示占位提示
        if not drones:
            self.drone_empty_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            self.drone_empty_label.place_forget()

        # 插入
        for d in drones:
            vendor_model = f"{d.vendor_str} / {d.product_type_str}"
            if len(vendor_model) > 28:
                vendor_model = vendor_model[:26] + ".."

            values = (
                d.drone_serial_num,
                vendor_model,
                str(d.detect_rssi),
                str(d.detect_snr),
                f"{d.drone_longitude:.5f}",
                f"{d.drone_latitude:.5f}",
                f"{d.height:.1f}",
                str(d.yaw_angle),
                str(d.east_speed),
                str(d.up_speed),
            )

            # 按 RSSI 标记颜色 tag
            tag = "strong" if d.detect_rssi > -50 else (
                "medium" if d.detect_rssi > -70 else (
                    "weak" if d.detect_rssi > -90 else "veryweak"
                )
            )
            self.drone_tree.insert("", tk.END, values=values, tags=(tag,))

        # 恢复选中
        if sel_serial:
            for item in self.drone_tree.get_children():
                if self.drone_tree.item(item, "values")[0] == sel_serial:
                    self.drone_tree.selection_set(item)
                    self.drone_tree.see(item)
                    break

        # 颜色 Tags
        self.drone_tree.tag_configure("strong", foreground=Theme.FG_GREEN)
        self.drone_tree.tag_configure("medium", foreground=Theme.FG_PRIMARY)
        self.drone_tree.tag_configure("weak", foreground=Theme.FG_ORANGE)
        self.drone_tree.tag_configure("veryweak", foreground=Theme.FG_RED)

        # 统计
        self.target_count_label.config(
            text=f"在线目标: {self.tracker.count}",
            fg=Theme.FG_GREEN if self.tracker.count > 0 else Theme.FG_SECONDARY
        )
        self.total_seen_label.config(text=f"累计发现: {self.total_drones_seen}")
        self.gbrid_count_label.config(text=f"报文: {self.gbrid_count}")

    # =========================================================================
    #  选中目标操作
    # =========================================================================

    def _on_drone_selected(self, event):
        sel = self.drone_tree.selection()
        if not sel:
            self.selected_serial = ""
            self._clear_detail()
            return
        serial_num = self.drone_tree.item(sel[0], "values")[0]
        self.selected_serial = serial_num
        drone = self.tracker.get(serial_num)
        if drone:
            self._update_detail(drone)

    def _update_detail(self, d: DroneInfo):
        """更新右侧详情面板"""
        self.detail_placeholder.place_forget()  # 隐藏占位提示

        vals = {
            "serial":     d.drone_serial_num,
            "vendor":     d.vendor_str,
            "model":      d.product_type_str,
            "d_lon":      f"{d.drone_longitude:.6f}",
            "d_lat":      f"{d.drone_latitude:.6f}",
            "height":     f"{d.height:.2f}",
            "alt":        f"{d.altitude:.2f}",
            "pressure":   f"{d.pressure:.2f}",
            "yaw":        f"{d.yaw_angle}°",
            "east_speed": f"{d.east_speed} m/s ({d.speed_kmh} km/h)",
            "up_speed":   f"{d.up_speed} m/s",
            "rssi":       f"{d.detect_rssi} dBm",
            "snr":        f"{d.detect_snr} dB",
            "p_lon":      f"{d.pilot_longitude:.6f}" if d.has_pilot_position else "--",
            "p_lat":      f"{d.pilot_latitude:.6f}" if d.has_pilot_position else "--",
            "p_height":   f"{d.pilot_height:.2f}" if d.has_pilot_position else "--",
            "drone_type": str(d.drone_type),
            "drone_class": str(d.drone_class),
            "state_info": str(d.state_info),
            "pos_err":    f"{d.position_error} m",
            "height_err": f"{d.height_error} m",
        }

        for key, lbl in self.detail_labels.items():
            if key in vals:
                lbl.config(text=vals[key])

        # 颜色标记
        if "rssi" in self.detail_labels:
            self.detail_labels["rssi"].config(fg=self._rssi_color(d.detect_rssi))
        if "snr" in self.detail_labels:
            self.detail_labels["snr"].config(fg=self._snr_color(d.detect_snr))

    def _clear_heartbeat(self):
        for lbl in self.hb_labels.values():
            lbl.config(text="--")
        self.hb_mode_label.config(
            text="🔍 当前模式: 仅心跳 — 等待无人机起飞...",
            fg=Theme.FG_YELLOW)

    def _clear_detail(self):
        for lbl in self.detail_labels.values():
            lbl.config(text="--")
        self.detail_placeholder.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # =========================================================================
    #  工具方法
    # =========================================================================

    def _rssi_color(self, rssi: int) -> str:
        if rssi > -50:
            return Theme.FG_GREEN
        elif rssi > -70:
            return Theme.FG_YELLOW
        elif rssi > -90:
            return Theme.FG_ORANGE
        else:
            return Theme.FG_RED

    def _snr_color(self, snr: int) -> str:
        if snr >= 20:
            return Theme.FG_GREEN
        elif snr >= 10:
            return Theme.FG_YELLOW
        elif snr >= 5:
            return Theme.FG_ORANGE
        else:
            return Theme.FG_RED

    def _log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-4]
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {text}\n")
        # 限制行数
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 200:
            self.log_text.delete('1.0', f'{lines - 150}.0')
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _on_close(self):
        if self.reader:
            self.reader.stop()
        self.root.destroy()


# =============================================================================
#  程序入口
# =============================================================================

def main():
    root = tk.Tk()
    app = RIDMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
