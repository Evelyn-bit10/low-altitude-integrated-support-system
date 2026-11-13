# ui/stand_assign_dialog.py
"""机位分配对话框"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QComboBox, QGroupBox,
                             QRadioButton, QButtonGroup,QWidget, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush

from typing import Dict, List, Optional
from datetime import datetime

from config_stands import DRONE_WIND_RESISTANCE
from utils.stand_store import list_stands
from utils.weather_analyzer import WeatherAnalyzer


class StandAssignDialog(QDialog):
    """机位分配对话框"""
    
    standAssigned = pyqtSignal(str, dict)  # 无人机ID, 机位配置

    def __init__(self, drone_id: str, drone_name: str, drone_model: str,
                 weather_data: dict, current_assignments: dict, parent=None):
        super().__init__(parent)
        self.drone_id = drone_id
        self.drone_name = drone_name
        self.drone_model = drone_model
        self.weather_data = weather_data
        self.current_assignments = current_assignments
        self.analyzer = WeatherAnalyzer()
        
        self.selected_stand = None
        self.setup_ui()
        self.load_stands()
        self.analyze_weather()
        
    def setup_ui(self):
        """初始化UI"""
        self.setWindowTitle(f"机位分配 - {self.drone_name}")
        self.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel(f"✈️ 无人机 {self.drone_name} 机位分配")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #303133; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # 天气分析
        self.weather_group = QGroupBox("当前天气分析")
        self.weather_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                padding-top: 15px;  /* 增加一点内边距避免压住标题 */
                margin-top: 10px;   /* 留出标题的位置 */
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 6px;
                font-size: 14px;
                color: #303133;
            }
        """)
        # 🚀 核心修改 1：解除 GroupBox 的强制高度，让它紧密包裹内容
        self.weather_group.setMinimumHeight(0)
        self.weather_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        weather_layout = QVBoxLayout()
        weather_layout.setContentsMargins(10, 15, 10, 10)
        weather_layout.setSpacing(8)
        
        self.weather_info = QLabel("正在分析天气...")
        self.weather_info.setStyleSheet("padding: 10px; background-color: #f5f7fa; border-radius: 4px; line-height: 1.5;")
        self.weather_info.setWordWrap(True)
        
        # 🚀 核心修改 2：解除文本框强制的 120px 高度，并设为垂直固定(自适应文字)
        self.weather_info.setMinimumHeight(0)
        self.weather_info.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.weather_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 🚀 核心修改 3：去掉后面的拉伸因子 "1"，禁止它吃掉对话框的剩余空间
        weather_layout.addWidget(self.weather_info)
        
        self.recommend_label = QLabel("推荐机位类型: ")
        self.recommend_label.setStyleSheet("color: #409EFF; font-weight: bold;")
        self.recommend_label.setWordWrap(True)
        weather_layout.addWidget(self.recommend_label)
        
        self.weather_group.setLayout(weather_layout)
        layout.addWidget(self.weather_group)
        
        # 无人机信息
        drone_info = QLabel(f"型号: {self.drone_model} | 抗风等级: {DRONE_WIND_RESISTANCE.get(self.drone_model, {}).get('level', '未知')}")
        drone_info.setStyleSheet("padding: 5px; color: #606266;")
        layout.addWidget(drone_info)
        
        # 筛选选项
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("显示:"))
        
        self.filter_group = QButtonGroup(self)
        self.filter_all = QRadioButton("全部机位")
        self.filter_indoor = QRadioButton("室内机位")
        self.filter_outdoor = QRadioButton("室外机位")
        self.filter_all.setChecked(True)
        
        for rb in [self.filter_all, self.filter_indoor, self.filter_outdoor]:
            self.filter_group.addButton(rb)
            filter_layout.addWidget(rb)
            
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # 机位表格
        self.stand_table = QTableWidget()
        self.stand_table.setColumnCount(6)
        self.stand_table.setHorizontalHeaderLabels(["选择", "机位ID", "名称", "类型", "状态", "推荐度"])
        self.stand_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stand_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.stand_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stand_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                alternate-background-color: #f9f9f9;
                gridline-color: #ebeef5;
                border-radius: 10px;
            }
            QHeaderView::section {
                background-color: #f5f7fa;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #ebeef5;
                font-weight: bold;
            }
            QTableWidget::item {
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background-color: rgba(64, 158, 255, 0.18);
                color: #303133;
            }
        """)
        
        layout.addWidget(self.stand_table)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.assign_btn = QPushButton("分配机位")
        self.assign_btn.setStyleSheet("""
            QPushButton {
                background-color: #67C23A;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #85ce61;
            }
            QPushButton:disabled {
                background-color: #dcdfe6;
                color: #909399;
            }
        """)
        self.assign_btn.clicked.connect(self.on_assign)
        self.assign_btn.setEnabled(False)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #909399;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #a6a9ad;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.assign_btn)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # 连接筛选信号
        self.filter_all.toggled.connect(self.load_stands)
        self.filter_indoor.toggled.connect(self.load_stands)
        self.filter_outdoor.toggled.connect(self.load_stands)
        
        # 连接表格选择信号
        self.stand_table.itemSelectionChanged.connect(self.on_selection_changed)
        
    def analyze_weather(self):
        """分析天气并显示建议"""
        risks = self.analyzer.analyze_weather_risk(self.weather_data)
        warning = self.analyzer.get_weather_warning(self.weather_data)
        
        # 显示天气信息
        weather_text = f"🌡️ 温度: {self.weather_data.get('temperature', '--')}°C | "
        weather_text += f"💧 湿度: {self.weather_data.get('humidity', '--')}% | "
        weather_text += f"💨 风速: {self.weather_data.get('wind_speed', '--')} m/s | "
        weather_text += f"☔ 降水: {self.weather_data.get('precipitation', 0)} mm\n"
        weather_text += f"📊 风险分析: {warning}\n"
        
        # 根据风险等级设置颜色
        if risks["overall_risk"] == "high":
            weather_text = "⚠️ " + weather_text
            self.weather_info.setStyleSheet("padding: 10px; background-color: #fef0f0; color: #F56C6C; border-radius: 4px;")
            recommend_text = "高风险天气，建议选择室内机位"
        elif risks["overall_risk"] == "medium":
            weather_text = "⚡ " + weather_text
            self.weather_info.setStyleSheet("padding: 10px; background-color: #fdf6ec; color: #E6A23C; border-radius: 4px;")
            recommend_text = "中风险天气，建议优先选择室内机位"
        else:
            self.weather_info.setStyleSheet("padding: 10px; background-color: #f0f9eb; color: #67C23A; border-radius: 4px;")
            recommend_text = "低风险天气，室内外机位均可"
            
        self.weather_info.setText(weather_text)
        self.recommend_label.setText(f"🎯 推荐机位类型: {recommend_text}")
        
        return risks
        


    def load_stands(self):
        """加载机位列表"""
        # 获取当前已占用的机位
        occupied_stands = list(self.current_assignments.values())
        
        print(f"当前已分配机位: {occupied_stands}")  # 调试信息
        print(f"当前无人机 {self.drone_id} 的机位: {self.current_assignments.get(self.drone_id)}")  # 调试信息
        
        # 根据筛选条件过滤
        stands_to_show = []
        for stand in list_stands():
            if self.filter_indoor.isChecked() and stand["type"] != "indoor":
                continue
            if self.filter_outdoor.isChecked() and stand["type"] != "outdoor":
                continue
            stands_to_show.append(stand)
        
        # 更新表格
        self.stand_table.setRowCount(len(stands_to_show))
        
        # 创建一个按钮组来确保单选
        self.radio_group = QButtonGroup(self)
        self.radio_group.setExclusive(True)  # 设置为互斥，确保只能选一个
        
        for row, stand in enumerate(stands_to_show):
            # 单选按钮列
            radio = QRadioButton()
            
            # 判断机位是否可用
            is_occupied_by_others = (stand["id"] in occupied_stands and 
                                    stand["id"] != self.current_assignments.get(self.drone_id))
            
            # 如果被其他无人机占用，则禁用
            radio.setEnabled(not is_occupied_by_others)
            
            # 如果是当前无人机的机位，默认选中
            if stand["id"] == self.current_assignments.get(self.drone_id):
                radio.setChecked(True)
                self.selected_stand = stand["id"]
                self.assign_btn.setEnabled(True)
            
            # 将单选按钮添加到按钮组
            self.radio_group.addButton(radio)
            
            radio_widget = QWidget()
            radio_layout = QHBoxLayout(radio_widget)
            radio_layout.addWidget(radio)
            radio_layout.setAlignment(Qt.AlignCenter)
            radio_layout.setContentsMargins(0, 0, 0, 0)
            self.stand_table.setCellWidget(row, 0, radio_widget)
            
            # 存储对应的radio按钮
            radio.stand_id = stand["id"]
            radio.row = row  # 存储行号方便后续使用
            
            # 机位ID
            id_item = QTableWidgetItem(stand["id"])
            id_item.setTextAlignment(Qt.AlignCenter)
            self.stand_table.setItem(row, 1, id_item)
            
            # 名称
            name_item = QTableWidgetItem(stand["name"])
            name_item.setTextAlignment(Qt.AlignCenter)
            self.stand_table.setItem(row, 2, name_item)
            
            # 类型
            type_text = "🏠 室内" if stand["type"] == "indoor" else "🌳 室外"
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(Qt.AlignCenter)
            self.stand_table.setItem(row, 3, type_item)
            
            # 状态
            if is_occupied_by_others:
                # 被其他无人机占用
                occupied_drone = None
                for d_id, s_id in self.current_assignments.items():
                    if s_id == stand["id"]:
                        occupied_drone = d_id
                        break
                status_text = f"❌ 被无人机 {occupied_drone} 占用"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QBrush(QColor("#F56C6C")))
                radio.setEnabled(False)
            elif stand["id"] == self.current_assignments.get(self.drone_id):
                # 当前无人机的机位
                status_text = "✅ 当前机位"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QBrush(QColor("#67C23A")))
            else:
                # 空闲机位
                status_text = "✅ 空闲"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QBrush(QColor("#67C23A")))
                
            status_item.setTextAlignment(Qt.AlignCenter)
            self.stand_table.setItem(row, 4, status_item)
            
            # 推荐度
            if not is_occupied_by_others:  # 只有可用机位才显示推荐度
                # 计算推荐度
                score = self.calculate_suitability(stand)
                if score >= 80:
                    score_text = "⭐ 推荐"
                    score_color = "#67C23A"
                elif score >= 50:
                    score_text = "✓ 可选"
                    score_color = "#E6A23C"
                else:
                    score_text = "○ 一般"
                    score_color = "#909399"
                    
                score_item = QTableWidgetItem(score_text)
                score_item.setForeground(QBrush(QColor(score_color)))
            else:
                score_item = QTableWidgetItem("--")
                score_item.setForeground(QBrush(QColor("#909399")))
                
            score_item.setTextAlignment(Qt.AlignCenter)
            self.stand_table.setItem(row, 5, score_item)
            
            # 连接单选按钮信号
            radio.toggled.connect(lambda checked, r=row: self.on_radio_toggled(checked, r))
            
        self.stand_table.resizeColumnsToContents()
        
        # 如果没有选中任何机位，禁用分配按钮
        if not self.selected_stand:
            self.assign_btn.setEnabled(False)
            
    def calculate_suitability(self, stand: dict) -> int:
        """计算机位适合度分数"""
        risks = self.analyzer.analyze_weather_risk(self.weather_data)
        drone_specs = DRONE_WIND_RESISTANCE.get(self.drone_model, {})
        score = 50  # 基础分
        
        # 根据天气调整分数
        if risks["overall_risk"] == "high":
            if stand["type"] == "indoor":
                score += 40
            else:
                score -= 30
        elif risks["overall_risk"] == "medium":
            if stand["type"] == "indoor":
                score += 25
            elif drone_specs.get("rain_proof", False):
                score += 10
            else:
                score -= 10
        
        # 根据风速调整
        wind_speed = self.weather_data.get("wind_speed", 0)
        max_wind = drone_specs.get("max_wind", 10)
        if wind_speed > max_wind and stand["type"] == "indoor":
            score += 30
        elif wind_speed > max_wind * 0.7 and stand["type"] == "outdoor":
            if "wind_proof" in stand.get("features", []):
                score += 15
            else:
                score -= 10
        
        # 根据优先级调整
        score += (3 - stand["priority"]) * 5
        
        # 确保分数在0-100之间
        return max(0, min(100, score))
        
    def on_radio_toggled(self, checked: bool, row: int):
        """单选按钮切换"""
        if checked:
            # 获取选中的机位
            radio_widget = self.stand_table.cellWidget(row, 0)
            if radio_widget:
                radio = radio_widget.layout().itemAt(0).widget()
                if radio:
                    self.selected_stand = radio.stand_id
                    print(f"选中机位: {self.selected_stand}")  # 调试信息
                    self.assign_btn.setEnabled(True)
            
    def on_selection_changed(self):
        """表格选择变化"""
        # 确保至少选中一行
        selected_rows = set()
        for item in self.stand_table.selectedItems():
            selected_rows.add(item.row())
        
        if selected_rows:
            row = list(selected_rows)[0]
            # 模拟点击对应的单选按钮
            radio_widget = self.stand_table.cellWidget(row, 0)
            if radio_widget:
                radio = radio_widget.layout().itemAt(0).widget()
                if radio and radio.isEnabled():
                    radio.setChecked(True)
                    
    def on_assign(self):
        """分配机位"""
        if not self.selected_stand:
            return
            
        # 查找机位信息
        stand_info = None
        for stand in list_stands():
            if stand["id"] == self.selected_stand:
                stand_info = stand.copy()
                stand_info["assigned_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                stand_info["drone_id"] = self.drone_id
                break
                
        if stand_info:
            self.standAssigned.emit(self.drone_id, stand_info)
            self.accept()
