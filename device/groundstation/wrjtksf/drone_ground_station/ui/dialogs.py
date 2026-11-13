# ui/dialogs.py
"""对话框UI组件"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit,
                             QComboBox, QSpinBox, QCheckBox, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSize, Qt
from config import DEFAULT_BAUDRATE, BAUDRATE_OPTIONS, DRONE_SVG_PATH


class AddDroneDialog(QDialog):
    """添加无人机对话框"""

    def __init__(self, existing_ids=None, parent=None):
        super().__init__(parent)
        self.existing_ids = existing_ids or []
        self.setWindowTitle("添加新无人机")
        self.setModal(True)
        self.setMinimumWidth(300)
        # 设置窗口标志，避免全屏时闪烁
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 无人机ID
        self.id_edit = QLineEdit()
        next_id = self._get_next_id()
        self.id_edit.setText(str(next_id))
        form_layout.addRow("ID:", self.id_edit)

        # 无人机名称
        self.name_edit = QLineEdit()
        self.name_edit.setText(f"无人机 {next_id}")
        form_layout.addRow("名称:", self.name_edit)

        # 图标
        self.emoji_combo = QComboBox()
        self.emoji_combo.setIconSize(QSize(24, 24))
        self.emoji_combo.addItem(QIcon(DRONE_SVG_PATH), "默认无人机")
        form_layout.addRow("图标:", self.emoji_combo)
        
        # 串口（自动检测 + 手动输入）
        port_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(180)
        self._populate_ports()
        port_layout.addWidget(self.port_combo, 1)
        btn_refresh_port = QPushButton("刷新")
        btn_refresh_port.clicked.connect(self._populate_ports)
        port_layout.addWidget(btn_refresh_port)
        form_layout.addRow("串口:", port_layout)

        # 波特率
        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(min(BAUDRATE_OPTIONS), max(BAUDRATE_OPTIONS))
        self.baud_spin.setValue(DEFAULT_BAUDRATE)
        self.baud_spin.setSingleStep(9600)
        form_layout.addRow("波特率:", self.baud_spin)

        # 【飞手信息】与该无人机一一对应的飞手信息
        self.pilot_name_edit = QLineEdit()
        self.pilot_email_edit = QLineEdit()
        self.pilot_phone_edit = QLineEdit()
        form_layout.addRow("飞手姓名:", self.pilot_name_edit)
        form_layout.addRow("飞手邮箱:", self.pilot_email_edit)
        form_layout.addRow("飞手电话:", self.pilot_phone_edit)

        # 自动连接选项
        self.auto_connect_check = QCheckBox("添加后自动连接")
        self.auto_connect_check.setChecked(False)
        form_layout.addRow("", self.auto_connect_check)

        layout.addLayout(form_layout)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        # 统一美化 OK / Cancel 按钮
        ok_btn = button_box.button(QDialogButtonBox.Ok)
        cancel_btn = button_box.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setStyleSheet("""
                QPushButton {
                    background-color: #409EFF;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #66b1ff; }
                QPushButton:pressed { background-color: #3a8ee6; }
            """)
        if cancel_btn:
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #909399;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #a6a9ad; }
                QPushButton:pressed { background-color: #848688; }
            """)
        button_box.setStyleSheet("QDialogButtonBox QPushButton{ min-height: 28px; }")

        layout.addWidget(button_box)

        # 无人机机型
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("无人机机型:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["自定义无人机", "大疆 M300", "大疆 M210", "大疆 M600",
                                   "大疆 Phantom 4", "大疆 Mavic 2", "大疆 Mavic 3", "大疆 Mini 3"])
        self.model_combo.setEditable(True)
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

    def _get_next_id(self):
        numeric_ids = []
        for id_str in self.existing_ids:
            try:
                numeric_ids.append(int(id_str))
            except ValueError:
                pass
        if numeric_ids: return max(numeric_ids) + 1
        return 5

    def _populate_ports(self):
        """刷新串口下拉列表。"""
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        self.port_combo.addItem("无")
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []
        for p in ports:
            if self.port_combo.findText(p) == -1:
                self.port_combo.addItem(p)
        if not ports:
            self.port_combo.addItem("（未检测到串口）")
        if current:
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def get_drone_config(self):
        port_text = self.port_combo.currentText().strip()
        if port_text == "无" or port_text.startswith("（"):
            port_text = ""
        return {
            "id": self.id_edit.text(),
            "name": self.name_edit.text(),
            "emoji": DRONE_SVG_PATH,
            "model": self.model_combo.currentText(),
            "port": port_text,
            "baud": self.baud_spin.value(),
            "pilot": {
                "name": self.pilot_name_edit.text().strip(),
                "email": self.pilot_email_edit.text().strip(),
                "phone": self.pilot_phone_edit.text().strip(),
            },
            "auto_connect": self.auto_connect_check.isChecked()
        }


class PilotInfoDialog(QDialog):
    """【飞手信息】飞手信息对话框（可在线修改 & 返回更新值）"""

    def __init__(self, pilot_name: str = "", pilot_email: str = "", pilot_phone: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("飞手信息")
        self.setModal(True)
        self.setMinimumWidth(320)
        self._build_ui(pilot_name, pilot_email, pilot_phone)

    def _build_ui(self, name: str, email: str, phone: str):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(name or "")
        self.email_edit = QLineEdit(email or "")
        self.phone_edit = QLineEdit(phone or "")

        self.email_edit.setPlaceholderText("example@domain.com")
        self.phone_edit.setPlaceholderText("手机号或座机号")

        form.addRow("飞手姓名:", self.name_edit)
        form.addRow("飞手邮箱:", self.email_edit)
        form.addRow("飞手电话:", self.phone_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)  # 直接绑 accept，重写 accept 拦截
        btns.rejected.connect(self.reject)

        ok_btn = btns.button(QDialogButtonBox.Ok)
        cancel_btn = btns.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setStyleSheet("""
                QPushButton {
                    background-color: #409EFF;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #66b1ff; }
            """)
        if cancel_btn:
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #909399;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #a6a9ad; }
            """)
        btns.setStyleSheet("QDialogButtonBox QPushButton{ min-height: 28px; }")
        layout.addWidget(btns)

    def get_values(self):
        # 【飞手信息】供外部读取修改后的飞手信息
        return {
            "name": self.name_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "phone": self.phone_edit.text().strip()
        }
        
    def accept(self):
        """重写 accept 方法，在点击确认时进行校验（防崩溃+查重版）"""
        try:
            values = self.get_values()
            name = values.get("name", "").strip()
            email = values.get("email", "").strip()
            phone = values.get("phone", "").strip()

            # 1. 格式校验
            if email and not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
                QMessageBox.warning(self, "格式错误", "请输入有效的邮箱地址！\n例如：example@domain.com")
                return

            if phone and not re.match(r'^1[3-9]\d{9}$', phone):
                QMessageBox.warning(self, "格式错误", "请输入有效的11位手机号码！")
                return

            # 2. 查重校验 (和主界面的其他无人机对比)
            main_window = self.parent()
            if hasattr(main_window, "drone_pilots") and hasattr(self, "current_drone_id"):
                current_id = self.current_drone_id
                for other_id, info in main_window.drone_pilots.items():
                    if str(other_id) == str(current_id):
                        continue # 跳过自己
                    
                    other_pilot_name = info.get("name", "")
                    other_email = info.get("email", "")
                    other_phone = info.get("phone", "")
                    
                    other_drone_name = f"无人机 {other_id}"
                    if hasattr(main_window, "drone_cards") and str(other_id) in main_window.drone_cards:
                        other_drone_name = main_window.drone_cards[str(other_id)].drone_name

                    if name and name == other_pilot_name:
                        QMessageBox.warning(self, "信息冲突", f"该姓名已被【{other_drone_name}】的飞手使用！\n请使用其他姓名以作区分。")
                        return
                    if email and email == other_email:
                        QMessageBox.warning(self, "信息冲突", f"该邮箱已被【{other_drone_name}】使用！\n请更换其他邮箱。")
                        return
                    if phone and phone == other_phone:
                        QMessageBox.warning(self, "信息冲突", f"该手机号已被【{other_drone_name}】使用！\n请更换其他手机号。")
                        return

            # 校验全部通过，执行原本的关闭并保存逻辑
            super().accept()

        except Exception as e:
            print(f"⚠️ 飞手信息校验异常: {e}")
            super().accept()
            

class AddStandDialog(QDialog):
    """机位添加/编辑弹窗"""
    def __init__(self, existing_stands, edit_mode=False, current_data=None, parent=None):
        super().__init__(parent)
        self.existing_stands = existing_stands  # 接收完整的现有字典: {id: {"name": "...", "type": "..."}}
        self.edit_mode = edit_mode              # 是否为编辑模式
        self.current_data = current_data or {}  # 编辑模式下传入的当前数据
        
        self.setWindowTitle("编辑机位" if edit_mode else "添加机位")
        self.setMinimumWidth(320)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # 1. 机位 ID
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("机位 ID:  "))
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("必需唯一 (例如: in_03, out_05)")
        id_layout.addWidget(self.id_input)
        layout.addLayout(id_layout)

        # 2. 机位名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("机位名称:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("用于显示 (例如: 室内机位 3)")
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # 3. 机位类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("机位类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["室内 (indoor)", "室外 (outdoor)"])
        self.type_combo.setStyleSheet("""
            QComboBox { border: 1px solid #dcdfe6; border-radius: 4px; padding: 4px 8px; }
            QComboBox::drop-down { border-left: 1px solid #dcdfe6; width: 20px; }
        """)
        type_layout.addWidget(self.type_combo)
        layout.addLayout(type_layout)

        # 如果是编辑模式，预填数据并锁定ID
        if self.edit_mode and self.current_data:
            self.id_input.setText(self.current_data.get("id", ""))
            self.id_input.setReadOnly(True)  # 编辑时不充许修改底层ID
            self.id_input.setStyleSheet("background-color: #f5f7fa; color: #909399;")
            
            self.name_input.setText(self.current_data.get("name", ""))
            
            if self.current_data.get("type") == "outdoor":
                self.type_combo.setCurrentIndex(1)
            else:
                self.type_combo.setCurrentIndex(0)

        # 4. 按钮区域
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("保存" if self.edit_mode else "确定")
        self.ok_btn.setStyleSheet("QPushButton { background-color: #409EFF; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; } QPushButton:hover { background-color: #66b1ff; }")
        self.ok_btn.clicked.connect(self.accept)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("QPushButton { background-color: #909399; color: white; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; } QPushButton:hover { background-color: #a6a9ad; }")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def accept(self):
        stand_id = self.id_input.text().strip()
        stand_name = self.name_input.text().strip()
        
        if not stand_name:
            stand_name = stand_id  

        # 1. 校验 ID 是否为空
        if not stand_id:
            QMessageBox.warning(self, "格式错误", "机位 ID 不能为空！")
            self.id_input.setFocus()
            return
            
        # 2. 添加模式下，校验 ID 是否重复
        if not self.edit_mode and stand_id in self.existing_stands:
            QMessageBox.warning(self, "信息冲突", f"机位 ID '{stand_id}' 已存在！\n请使用其他编号。")
            self.id_input.selectAll()
            self.id_input.setFocus()
            return

        # 3. 校验名称是否重复
        for s_id, s_info in self.existing_stands.items():
            if self.edit_mode and s_id == self.current_data.get("id"):
                continue # 编辑模式下，跳过自己原来的名字
                
            existing_name = s_info.get("name", "")
            if stand_name == existing_name:
                QMessageBox.warning(self, "信息冲突", f"机位名称【{stand_name}】已被使用（占用ID: {s_id}）！\n请更换其他名称以作区分。")
                self.name_input.selectAll()
                self.name_input.setFocus()
                return

        # 全部通过，保存关闭
        super().accept()

    def get_data(self):
        """获取填写的机位数据"""
        stand_id = self.id_input.text().strip()
        stand_name = self.name_input.text().strip()
        if not stand_name:
            stand_name = stand_id 

        stand_type = "indoor" if self.type_combo.currentIndex() == 0 else "outdoor"
        
        return {
            "id": stand_id,
            "name": stand_name,
            "type": stand_type
        }
