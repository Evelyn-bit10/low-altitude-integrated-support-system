# # ui/drone_card.py
# """无人机信息卡片UI组件"""
# from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
#                              QPushButton, QMessageBox)
# from PyQt5.QtCore import Qt, pyqtSignal
# from PyQt5.QtSvg import QSvgWidget  # 引入 SVG 支持
# from config import DRONE_SVG_PATH
#
# class DroneInfoCard(QFrame):
#     removeClicked = pyqtSignal(str)
#     connectClicked = pyqtSignal(str, bool)
#     assignStandClicked = pyqtSignal(str)
#     releaseStandClicked = pyqtSignal(str)
#
#     def __init__(self, drone_config, parent=None):
#         super().__init__(parent)
#         self.drone_id = str(drone_config["id"])
#         self.drone_name = drone_config["name"]
#         self.drone_emoji = drone_config["emoji"]
#         self.drone_model = drone_config.get("model", "自定义无人机")
#         self.port = drone_config.get("port", "COM?")
#         self.baud = drone_config.get("baud", 57600)
#         self.is_connected = False
#         self.assigned_stand = None
#         self.stand_info = None
#         self.setup_ui()
#
#     def setup_ui(self):
#         self.setFrameShape(QFrame.StyledPanel)
#         self.setFrameShadow(QFrame.Raised)
#
#         self.setStyleSheet("""
#             DroneInfoCard { background-color: #ffffff; border: 1px solid #dcdfe6; border-radius: 8px; }
#             DroneInfoCard[connected="true"] { border: 2px solid #67C23A; background-color: #f0f9eb; }
#             DroneInfoCard[connected="false"] { border: 1px solid #dcdfe6; }
#             QLabel { font-family: 'Microsoft YaHei', sans-serif; }
#             QLabel#titleLabel { font-size: 16px; font-weight: bold; color: #303133; padding: 4px 0px; }
#             QLabel#standLabel { font-size: 12px; color: #67C23A; background-color: #f0f9eb; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
#             QLabel#standLabel[type="indoor"] { background-color: #e1f5fe; color: #0288d1; }
#             QLabel#standLabel[type="outdoor"] { background-color: #e8f5e8; color: #2e7d32; }
#             QLabel#valueLabel { font-size: 18px; font-weight: bold; color: #409EFF; background-color: #f4f4f5; padding: 8px 2px; border-radius: 6px; margin-top: 2px; }
#             QLabel#infoLabel { font-size: 13px; color: #606266; font-weight: bold; }
#             QLabel#portLabel { font-size: 12px; color: #909399; background-color: #f4f4f5; padding: 2px 8px; border-radius: 10px; }
#             QPushButton#removeBtn { background-color: transparent; border: none; color: #f56c6c; font-size: 16px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
#             QPushButton#removeBtn:hover { background-color: #fef0f0; }
#             QPushButton#assignBtn { background-color: #409EFF; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-size: 13px; font-weight: bold; min-width: 80px; }
#             QPushButton#assignBtn:hover { background-color: #66b1ff; }
#             QPushButton#assignBtn[assigned="true"] { background-color: #67C23A; }
#             QPushButton#assignBtn[assigned="true"]:hover { background-color: #85ce61; }
#             QPushButton#connectBtn { border: none; border-radius: 4px; padding: 6px 12px; font-size: 13px; font-weight: bold; min-width: 80px; }
#             QPushButton#connectBtn[connected="true"] { background-color: #f56c6c; color: white; }
#             QPushButton#connectBtn[connected="true"]:hover { background-color: #f78989; }
#             QPushButton#connectBtn[connected="false"] { background-color: #67C23A; color: white; }
#             QPushButton#connectBtn[connected="false"]:hover { background-color: #85ce61; }
#             QPushButton#releaseBtn { background-color: #f56c6c; color: white; border: none; border-radius: 4px; padding: 4px 8px; font-size: 12px; margin-top: 4px; }
#             QPushButton#releaseBtn:hover { background-color: #f78989; }
#         """)
#
#         layout = QVBoxLayout(self)
#         layout.setSpacing(8)
#         layout.setContentsMargins(12, 10, 12, 10)
#
#         # ========== 第一行：标题 ==========
#         title_layout = QHBoxLayout()
#
#         # --- 修改点：渲染 SVG 图标，读取自 config ---
#         try:
#             self.icon_svg = QSvgWidget(DRONE_SVG_PATH)
#             self.icon_svg.setFixedSize(24, 24)
#             title_layout.addWidget(self.icon_svg)
#         except Exception:
#             pass
#
#         title_label = QLabel(self.drone_name)
#         title_label.setObjectName("titleLabel")
#         title_layout.addWidget(title_label)
#
#         title_layout.addStretch()
#
#         self.port_label = QLabel(f"{self.port} @ {self.baud}")
#         self.port_label.setObjectName("portLabel")
#         title_layout.addWidget(self.port_label)
#
#         self.remove_btn = QPushButton("✕")
#         self.remove_btn.setObjectName("removeBtn")
#         self.remove_btn.setFixedSize(24, 24)
#         self.remove_btn.clicked.connect(lambda: self.removeClicked.emit(self.drone_id))
#         title_layout.addWidget(self.remove_btn)
#
#         layout.addLayout(title_layout)
#
#         # ========== 第二行：机位标签、分配按钮、连接按钮 ==========
#         button_row_layout = QHBoxLayout()
#         self.stand_label = QLabel("")
#         self.stand_label.setObjectName("standLabel")
#         self.stand_label.hide()
#         button_row_layout.addWidget(self.stand_label)
#         button_row_layout.addStretch()
#
#         self.assign_btn = QPushButton("📋 分配")
#         self.assign_btn.setObjectName("assignBtn")
#         self.assign_btn.setProperty("assigned", False)
#         self.assign_btn.clicked.connect(lambda: self.assignStandClicked.emit(self.drone_id))
#         button_row_layout.addWidget(self.assign_btn)
#
#         self.connect_btn = QPushButton("连接")
#         self.connect_btn.setObjectName("connectBtn")
#         self.connect_btn.setProperty("connected", False)
#         self.connect_btn.clicked.connect(self._on_connect_clicked)
#         button_row_layout.addWidget(self.connect_btn)
#         layout.addLayout(button_row_layout)
#
#         line = QFrame()
#         line.setFrameShape(QFrame.HLine)
#         line.setStyleSheet("background-color: #ebeef5; max-height: 1px; border: none; margin: 5px 0;")
#         layout.addWidget(line)
#
#         # ========== 第三行：遥测数据 ==========
#         self.lat_value = QLabel("--")
#         self.lng_value = QLabel("--")
#         self.alt_value = QLabel("--")
#         self.battery_value = QLabel("--")
#         self.sats_value = QLabel("--")
#
#         coord_layout = QHBoxLayout()
#         coord_layout.setSpacing(10)
#         coord_layout.addLayout(self._create_data_box("纬度 (Lat)", self.lat_value))
#         coord_layout.addLayout(self._create_data_box("经度 (Lng)", self.lng_value))
#         layout.addLayout(coord_layout)
#
#         stats_layout = QHBoxLayout()
#         stats_layout.setSpacing(6)
#         stats_layout.addLayout(self._create_data_box("高度(m)", self.alt_value))
#         stats_layout.addLayout(self._create_data_box("电量(%)", self.battery_value))
#         stats_layout.addLayout(self._create_data_box("卫星", self.sats_value))
#         layout.addLayout(stats_layout)
#
#         # ========== 第四行：机位详细信息（折叠式） ==========
#         self.stand_info_widget = QFrame()
#         self.stand_info_widget.setStyleSheet("QFrame { background-color: #f8f9fa; border-radius: 6px; margin-top: 8px; padding: 8px; }")
#         self.stand_info_widget.hide()
#
#         stand_info_layout = QVBoxLayout(self.stand_info_widget)
#         stand_info_layout.setContentsMargins(8, 8, 8, 8)
#         stand_info_layout.setSpacing(4)
#
#         self.stand_detail_label = QLabel()
#         self.stand_detail_label.setWordWrap(True)
#         self.stand_detail_label.setStyleSheet("font-size: 12px; color: #606266; line-height: 1.5;")
#         stand_info_layout.addWidget(self.stand_detail_label)
#
#         self.release_stand_btn = QPushButton("释放机位")
#         self.release_stand_btn.setObjectName("releaseBtn")
#         self.release_stand_btn.clicked.connect(self._on_release_stand)
#         stand_info_layout.addWidget(self.release_stand_btn)
#
#         layout.addWidget(self.stand_info_widget)
#
#         self.setProperty("connected", False)
#         self.style().polish(self)
#
#     def _create_data_box(self, label_text, value_label):
#         vbox = QVBoxLayout()
#         vbox.setSpacing(2)
#         lbl = QLabel(label_text)
#         lbl.setObjectName("infoLabel")
#         lbl.setAlignment(Qt.AlignCenter)
#         value_label.setObjectName("valueLabel")
#         value_label.setAlignment(Qt.AlignCenter)
#         vbox.addWidget(lbl)
#         vbox.addWidget(value_label)
#         return vbox
#
#     def _on_connect_clicked(self):
#         self.connectClicked.emit(self.drone_id, not self.is_connected)
#
#     def _on_release_stand(self):
#         if not self.assigned_stand or not self.stand_info: return
#         stand_name = self.stand_info.get('name', self.assigned_stand)
#         parent_window = self.window() if self.window() else None
#         reply = QMessageBox.question(
#             parent_window or self, "确认释放机位",
#             f"确定要释放机位 {stand_name} 吗？\n\n释放后该机位将变为空闲状态。",
#             QMessageBox.Yes | QMessageBox.No, QMessageBox.No
#         )
#         if reply == QMessageBox.Yes:
#             self.releaseStandClicked.emit(self.drone_id)
#
#     def set_connected(self, connected):
#         self.is_connected = connected
#         if connected:
#             self.connect_btn.setText("断开")
#             self.connect_btn.setProperty("connected", True)
#             self.setProperty("connected", True)
#         else:
#             self.connect_btn.setText("连接")
#             self.connect_btn.setProperty("connected", False)
#             self.setProperty("connected", False)
#         self.connect_btn.style().polish(self.connect_btn)
#         self.style().polish(self)
#
#     def set_assigned_stand(self, stand_id, stand_info=None):
#         self.assigned_stand = stand_id
#         self.stand_info = stand_info
#         if stand_id and stand_info:
#             stand_type = stand_info.get("type", "outdoor")
#             type_icon = "🏠" if stand_type == "indoor" else "🌳"
#             self.stand_label.setText(f"{type_icon} {stand_info.get('name', stand_id)}")
#             self.stand_label.setProperty("type", stand_type)
#             self.stand_label.show()
#             self.assign_btn.setText("✓ 已分配")
#             self.assign_btn.setProperty("assigned", True)
#             detail_text = f"📌 机位: {stand_info.get('name', stand_id)}\n"
#             detail_text += f"🏷️ 类型: {'室内' if stand_type == 'indoor' else '室外'}\n"
#             detail_text += f"⏰ 分配时间: {stand_info.get('assigned_time', '--')}\n"
#             detail_text += f"📝 描述: {stand_info.get('description', '--')}"
#             self.stand_detail_label.setText(detail_text)
#             self.stand_info_widget.show()
#         else:
#             self.stand_label.hide()
#             self.assign_btn.setText("📋 分配")
#             self.assign_btn.setProperty("assigned", False)
#             self.stand_info_widget.hide()
#         self.assign_btn.style().polish(self.assign_btn)
#
#     def update_data(self, lat, lng, alt, battery, sats):
#         base_style = "QLabel#valueLabel { padding: 8px 2px; border-radius: 6px; "
#         self.lat_value.setText(f"{lat:.6f}" if lat is not None else "--")
#         self.lng_value.setText(f"{lng:.6f}" if lng is not None else "--")
#         self.alt_value.setText(f"{alt:.1f}" if alt is not None else "--")
#         if battery is not None and battery >= 0:
#             self.battery_value.setText(f"{battery:.0f}")
#             if battery < 20: self.battery_value.setStyleSheet(base_style + "background-color:#fef0f0; color:#F56C6C;}")
#             elif battery < 50: self.battery_value.setStyleSheet(base_style + "background-color:#fdf6ec; color:#E6A23C;}")
#             else: self.battery_value.setStyleSheet(base_style + "background-color:#f0f9eb; color:#67C23A;}")
#         else:
#             self.battery_value.setText("--")
#             self.battery_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")
#         if sats is not None and sats >= 0:
#             self.sats_value.setText(f"{sats:.0f}")
#             if sats < 6: self.sats_value.setStyleSheet(base_style + "background-color:#fdf6ec; color:#E6A23C;}")
#             else: self.sats_value.setStyleSheet(base_style + "background-color:#f0f9eb; color:#67C23A;}")
#         else:
#             self.sats_value.setText("--")
#             self.sats_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")

# ui/drone_card.py
"""无人机信息卡片UI组件"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QMessageBox, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtSvg import QSvgWidget  # 引入 SVG 支持
from config import DRONE_SVG_PATH


class DroneInfoCard(QFrame):
    removeClicked = pyqtSignal(str)
    connectClicked = pyqtSignal(str, bool)
    assignStandClicked = pyqtSignal(str)
    releaseStandClicked = pyqtSignal(str)
    pilotInfoClicked = pyqtSignal(str)  # 【飞手信息】新增：卡片内“飞手信息”按钮点击信号

    def __init__(self, drone_config, parent=None):
        super().__init__(parent)
        self.drone_id = str(drone_config["id"])
        self.drone_name = drone_config["name"]
        self.drone_emoji = drone_config["emoji"]
        self.drone_model = drone_config.get("model", "自定义无人机")
        self.port = drone_config.get("port", "COM?")
        self.baud = drone_config.get("baud", 57600)
        self.is_connected = False
        self.assigned_stand = None
        self.stand_info = None
        self.setup_ui()

    def setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        self.setStyleSheet("""
            DroneInfoCard { background-color: #ffffff; border: 1px solid #dcdfe6; border-radius: 8px; }
            DroneInfoCard[connected="true"] { border: 2px solid #67C23A; background-color: #f0f9eb; }
            DroneInfoCard[connected="false"] { border: 1px solid #dcdfe6; }
            DroneInfoCard[assigned="true"] { border: 2px solid #95d475; background-color: #f3faef; }
            QLabel { font-family: 'Microsoft YaHei', sans-serif; }
            QLabel#titleLabel { font-size: 16px; font-weight: bold; color: #303133; padding: 4px 0px; }
            QLabel#standLabel { font-size: 12px; color: #67C23A; background-color: #f0f9eb; padding: 4px 10px; border-radius: 12px; font-weight: bold; }
            QLabel#standLabel[type="indoor"] { background-color: #e1f5fe; color: #0288d1; }
            QLabel#standLabel[type="outdoor"] { background-color: #e8f5e8; color: #2e7d32; }
            QLabel#titleStandLabel { font-size: 12px; color: #67C23A; background-color: #f0f9eb; padding: 4px 10px; border-radius: 999px; font-weight: bold; }
            QLabel#titleStandLabel[type="indoor"] { background-color: #e1f5fe; color: #0288d1; }
            QLabel#titleStandLabel[type="outdoor"] { background-color: #e8f5e8; color: #2e7d32; }
            QLabel#valueLabel { font-size: 18px; font-weight: bold; color: #409EFF; background-color: #f4f4f5; padding: 8px 2px; border-radius: 6px; margin-top: 2px; }
            QLabel#infoLabel { font-size: 13px; color: #606266; font-weight: bold; }
            QLabel#portLabel { font-size: 12px; color: #909399; background-color: #f4f4f5; padding: 2px 8px; border-radius: 10px; }
            QPushButton#removeBtn { background-color: transparent; border: none; color: #f56c6c; font-size: 16px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
            QPushButton#removeBtn:hover { background-color: #fef0f0; }
            QPushButton#assignBtn { background-color: #409EFF; color: white; border: none; border-radius: 4px; padding: 5px 10px; font-size: 13px; font-weight: bold; min-width: 60px; }
            QPushButton#assignBtn:hover { background-color: #66b1ff; }
            QPushButton#assignBtn[assigned="true"] { background-color: #67C23A; }
            QPushButton#assignBtn[assigned="true"]:hover { background-color: #85ce61; }
            QPushButton#connectBtn { border: none; border-radius: 4px; padding: 5px 10px; font-size: 13px; font-weight: bold; min-width: 60px; }
            QPushButton#connectBtn[connected="true"] { background-color: #f56c6c; color: white; }
            QPushButton#connectBtn[connected="true"]:hover { background-color: #f78989; }
            QPushButton#connectBtn[connected="false"] { background-color: #67C23A; color: white; }
            QPushButton#connectBtn[connected="false"]:hover { background-color: #85ce61; }
            QPushButton#releaseBtn { background-color: #f56c6c; color: white; border: none; border-radius: 4px; padding: 4px 8px; font-size: 12px; margin-top: 4px; }
            QPushButton#releaseBtn:hover { background-color: #f78989; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 7, 8, 7)

        # ========== 第一行：标题 ==========
        title_layout = QHBoxLayout()

        # --- 修改点：渲染 SVG 图标，读取自 config ---
        try:
            self.icon_svg = QSvgWidget(DRONE_SVG_PATH)
            self.icon_svg.setFixedSize(24, 24)
            title_layout.addWidget(self.icon_svg)
        except Exception:
            pass

        title_label = QLabel(self.drone_name)
        title_label.setObjectName("titleLabel")
        # 让标题可伸缩（在窄面板时优先保证“无人机名 + 机位徽标”可见）
        title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_layout.addWidget(title_label)

        # 分配后把机位显示在“无人机标题”后面
        self.title_stand_label = QLabel("")
        self.title_stand_label.setObjectName("titleStandLabel")
        self.title_stand_label.hide()
        # 机位徽标尽量固定宽度，避免被右侧端口信息挤没
        self.title_stand_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        title_layout.addWidget(self.title_stand_label)

        title_layout.addStretch()

        self.port_label = QLabel(f"{self.port} @ {self.baud}")
        self.port_label.setObjectName("portLabel")
        # 右侧端口信息在窄面板时允许被压缩/省略，不要把机位徽标挤走
        self.port_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.port_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.port_label.setMaximumWidth(120)
        title_layout.addWidget(self.port_label)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("removeBtn")
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.clicked.connect(lambda: self.removeClicked.emit(self.drone_id))
        title_layout.addWidget(self.remove_btn)

        layout.addLayout(title_layout)

        # ========== 第二行：机位标签、分配按钮、连接按钮、飞手信息按钮 并排 ==========
        button_row_layout = QHBoxLayout()
        self.stand_label = QLabel("")
        self.stand_label.setObjectName("standLabel")
        self.stand_label.hide()
        button_row_layout.addWidget(self.stand_label)
        button_row_layout.addStretch()

        self.assign_btn = QPushButton("📋 分配")
        self.assign_btn.setObjectName("assignBtn")
        self.assign_btn.setProperty("assigned", False)
        self.assign_btn.clicked.connect(lambda: self.assignStandClicked.emit(self.drone_id))
        button_row_layout.addWidget(self.assign_btn)

        # 【飞手信息】飞手信息按钮（与分配/连接并排）
        self.pilot_btn = QPushButton("👨‍✈️ 飞手")
        self.pilot_btn.setObjectName("assignBtn")  # 复用蓝色主按钮样式
        self.pilot_btn.clicked.connect(lambda: self.pilotInfoClicked.emit(self.drone_id))
        button_row_layout.addWidget(self.pilot_btn)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.setProperty("connected", False)
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        button_row_layout.addWidget(self.connect_btn)
        layout.addLayout(button_row_layout)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #ebeef5; max-height: 1px; border: none; margin: 5px 0;")
        layout.addWidget(line)

        # ========== 第三行：遥测数据 ==========
        self.lat_value = QLabel("--")
        self.lng_value = QLabel("--")
        self.alt_value = QLabel("--")
        self.battery_value = QLabel("--")
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
        stats_layout.addLayout(self._create_data_box("卫星", self.sats_value))
        layout.addLayout(stats_layout)

        # ========== 第四行：机位详细信息（折叠式） ==========
        self.stand_info_widget = QFrame()
        self.stand_info_widget.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 6px; margin-top: 8px; padding: 8px; }")
        self.stand_info_widget.hide()

        stand_info_layout = QVBoxLayout(self.stand_info_widget)
        stand_info_layout.setContentsMargins(6, 6, 6, 6)
        stand_info_layout.setSpacing(3)

        self.stand_detail_label = QLabel()
        self.stand_detail_label.setWordWrap(True)
        self.stand_detail_label.setStyleSheet("font-size: 12px; color: #606266; line-height: 1.5;")
        stand_info_layout.addWidget(self.stand_detail_label)

        self.release_stand_btn = QPushButton("释放机位")
        self.release_stand_btn.setObjectName("releaseBtn")
        self.release_stand_btn.clicked.connect(self._on_release_stand)
        stand_info_layout.addWidget(self.release_stand_btn)

        layout.addWidget(self.stand_info_widget)

        self.setProperty("connected", False)
        self.setProperty("assigned", False)
        self.style().polish(self)

    def _create_data_box(self, label_text, value_label):
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

    def _on_connect_clicked(self):
        self.connectClicked.emit(self.drone_id, not self.is_connected)

    def _on_release_stand(self):
        if not self.assigned_stand or not self.stand_info: return
        stand_name = self.stand_info.get('name', self.assigned_stand)
        parent_window = self.window() if self.window() else None
        msg = QMessageBox(parent_window or self)
        msg.setWindowTitle("确认释放机位")
        msg.setText(f"确定要释放机位 {stand_name} 吗？\n\n释放后该机位将变为空闲状态。")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        yes_btn = msg.button(QMessageBox.Yes)
        no_btn = msg.button(QMessageBox.No)
        if yes_btn:
            yes_btn.setStyleSheet("""
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
            """)
        if no_btn:
            no_btn.setStyleSheet("""
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
            """)
        reply = msg.exec_()
        if reply == QMessageBox.Yes:
            self.releaseStandClicked.emit(self.drone_id)

    def set_connected(self, connected):
        self.is_connected = connected
        if connected:
            self.connect_btn.setText("断开")
            self.connect_btn.setProperty("connected", True)
            self.setProperty("connected", True)
        else:
            self.connect_btn.setText("连接")
            self.connect_btn.setProperty("connected", False)
            self.setProperty("connected", False)
        self.connect_btn.style().polish(self.connect_btn)
        self.style().polish(self)

    def set_assigned_stand(self, stand_id, stand_info=None):
        self.assigned_stand = stand_id
        self.stand_info = stand_info
        if stand_id and stand_info:
            stand_type = stand_info.get("type", "outdoor")
            # 分配后不再显示标题后的机位徽标，改为整卡高亮
            self.title_stand_label.hide()
            self.stand_label.hide()
            self.setProperty("assigned", True)
            self.assign_btn.setText("✓ 已分配")
            self.assign_btn.setProperty("assigned", True)

            stand_name = stand_info.get("name", stand_id)
            detail_text = f"📌 机位: {stand_name}    ID: {stand_id}\n"
            detail_text += f"🏷️ 类型: {'室内' if stand_type == 'indoor' else '室外'}\n"
            detail_text += f"⏰ 分配时间: {stand_info.get('assigned_time', '--')}\n"
            detail_text += f"📝 描述: {stand_info.get('description', '--')}"
            self.stand_detail_label.setText(detail_text)
            self.stand_info_widget.show()
            # 通知父容器调整大小
            self.updateGeometry()
        else:
            self.title_stand_label.hide()
            self.stand_label.hide()
            self.setProperty("assigned", False)
            self.assign_btn.show()
            self.pilot_btn.show()
            self.connect_btn.show()
            self.assign_btn.setText("📋 分配")
            self.assign_btn.setProperty("assigned", False)
            self.stand_info_widget.hide()
            # 通知父容器调整大小
            self.updateGeometry()
        self.assign_btn.style().polish(self.assign_btn)
        self.style().polish(self)

    def update_data(self, lat, lng, alt, battery, sats):
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
        if sats is not None and sats >= 0:
            self.sats_value.setText(f"{sats:.0f}")
            if sats < 6:
                self.sats_value.setStyleSheet(base_style + "background-color:#fdf6ec; color:#E6A23C;}")
            else:
                self.sats_value.setStyleSheet(base_style + "background-color:#f0f9eb; color:#67C23A;}")
        else:
            self.sats_value.setText("--")
            self.sats_value.setStyleSheet(base_style + "background-color:#f4f4f5; color:#409EFF;}")

    def clear_data(self):
        """断开连接后清空该无人机数据显示（不移除卡片）"""
        self.update_data(None, None, None, None, None)