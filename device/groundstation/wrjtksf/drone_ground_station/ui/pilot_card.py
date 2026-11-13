"""【飞手信息】卡片UI组件（用于飞手集中管理面板）"""

from typing import Optional

from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal


class _DblClickEditableLineEdit(QLineEdit):
    """双击后通知外部进入可编辑模式。"""

    doubleClickedSignal = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClickedSignal.emit()
        super().mouseDoubleClickEvent(event)


class PilotInfoCard(QFrame):
    pilotUpdated = pyqtSignal(str, dict)   # drone_id, {name,email,phone}
    pilotViewRequested = pyqtSignal(str)   # drone_id

    def __init__(self, drone_id: str, drone_name: str, pilot: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.drone_id = str(drone_id)
        self.drone_name = drone_name
        self._suppress = False
        self._last_emitted = {"name": "", "email": "", "phone": ""}

        pilot = pilot or {}
        # 统一使用“同一套输入控件”，仅通过 readOnly 控制是否可编辑（双击才可编辑）
        self._name_edit = _DblClickEditableLineEdit()
        self._email_edit = _DblClickEditableLineEdit()
        self._phone_edit = _DblClickEditableLineEdit()

        self._build_ui()
        self.set_pilot(pilot.get("name", ""), pilot.get("email", ""), pilot.get("phone", ""))

    def _build_ui(self):
        self.setObjectName("pilotInfoCard")
        self.setStyleSheet("""
            #pilotInfoCard {
                background-color: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 8px;
            }
            QLabel { font-family: 'Microsoft YaHei', sans-serif; }
            QLabel#titleLabel { font-size: 14px; font-weight: bold; color: #303133; padding: 4px 0px; }
            QLabel#fieldLabel { font-size: 12px; color: #606266; font-weight: bold; }
            QPushButton#viewBtn {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
                min-width: 60px;
            }
            QPushButton#viewBtn:hover { background-color: #66b1ff; }
            QLineEdit {
                background-color: #f8f9fa;
                border: 1px solid #ebeef5;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(64, 158, 255, 0.7);
                outline: none;
            }
            QLineEdit[readOnly="true"] {
                background-color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 7, 8, 7)

        # Title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        icon = QLabel("👨‍✈️")
        icon.setStyleSheet("font-size: 15px;")
        title_row.addWidget(icon)

        self._title_label = QLabel(self.drone_name)
        self._title_label.setObjectName("titleLabel")
        title_row.addWidget(self._title_label)

        id_label = QLabel(f"ID: {self.drone_id}")
        id_label.setStyleSheet("font-size: 12px; color: #909399; background-color: #f4f4f5; padding: 2px 8px; border-radius: 10px;")
        title_row.addWidget(id_label)
        title_row.addStretch(1)

        self.view_btn = QPushButton("查看")
        self.view_btn.setObjectName("viewBtn")
        # 缩小右侧面板“卡片宽度”时，控制按钮不会撑大最小宽度
        self.view_btn.setMinimumWidth(60)
        self.view_btn.clicked.connect(lambda: self.pilotViewRequested.emit(self.drone_id))
        title_row.addWidget(self.view_btn)

        layout.addLayout(title_row)

        # Fields (展示 QLabel + 编辑 QLineEdit)
        def make_field(label_text: str, editor: QLineEdit, placeholder: str):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            lbl = QLabel(label_text)
            lbl.setObjectName("fieldLabel")
            lbl.setFixedWidth(54)
            row.addWidget(lbl)

            editor.setPlaceholderText(placeholder)
            editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            editor.setReadOnly(True)  # 默认只读
            row.addWidget(editor, 1)
            return row

        layout.addLayout(make_field("飞手姓名", self._name_edit, "请输入姓名"))
        layout.addLayout(make_field("飞手邮箱", self._email_edit, "请输入邮箱"))
        layout.addLayout(make_field("飞手电话", self._phone_edit, "请输入电话"))

        # 双击进入可编辑（不需要切换两套控件）
        self._name_edit.doubleClickedSignal.connect(lambda: self._begin_edit("name"))
        self._email_edit.doubleClickedSignal.connect(lambda: self._begin_edit("email"))
        self._phone_edit.doubleClickedSignal.connect(lambda: self._begin_edit("phone"))

        # 编辑完成 -> 只读 + 发信号（值变化才发）
        self._name_edit.editingFinished.connect(lambda: self._commit_edit("name"))
        self._email_edit.editingFinished.connect(lambda: self._commit_edit("email"))
        self._phone_edit.editingFinished.connect(lambda: self._commit_edit("phone"))

        # 回车同样提交
        self._name_edit.returnPressed.connect(lambda: self._commit_edit("name"))
        self._email_edit.returnPressed.connect(lambda: self._commit_edit("email"))
        self._phone_edit.returnPressed.connect(lambda: self._commit_edit("phone"))

    def set_pilot(self, name: str, email: str, phone: str):
        """Programmatic update (suppresses change emission)."""
        self._suppress = True
        try:
            self._name_edit.setText((name or "").strip())
            self._email_edit.setText((email or "").strip())
            self._phone_edit.setText((phone or "").strip())
            # 仍保持只读，避免程序刷新触发用户编辑逻辑
            self._name_edit.setReadOnly(True)
            self._email_edit.setReadOnly(True)
            self._phone_edit.setReadOnly(True)
        finally:
            self._suppress = False

    def set_drone_name(self, drone_name: str):
        """更新卡片标题（无人机名称）。"""
        self.drone_name = drone_name
        if hasattr(self, "_title_label") and self._title_label is not None:
            self._title_label.setText(drone_name or "")

    def _begin_edit(self, field: str):
        if self._suppress:
            return
        # 只切“可编辑态”，控件本身不切换（避免显示态/编辑态两套 UI）
        # 先全部只读，避免多个输入框同时可编辑
        self._name_edit.setReadOnly(True)
        self._email_edit.setReadOnly(True)
        self._phone_edit.setReadOnly(True)

        if field == "name":
            self._name_edit.setReadOnly(False)
            self._name_edit.setFocus()
            self._name_edit.selectAll()
        elif field == "email":
            self._email_edit.setReadOnly(False)
            self._email_edit.setFocus()
            self._email_edit.selectAll()
        else:
            self._phone_edit.setReadOnly(False)
            self._phone_edit.setFocus()
            self._phone_edit.selectAll()

    def _commit_edit(self, field: str):
        if self._suppress:
            return

        data = {
            "name": (self._name_edit.text() or "").strip(),
            "email": (self._email_edit.text() or "").strip(),
            "phone": (self._phone_edit.text() or "").strip(),
        }

        # 回到只读
        self._name_edit.setReadOnly(True)
        self._email_edit.setReadOnly(True)
        self._phone_edit.setReadOnly(True)

        if data == self._last_emitted:
            return
        self._last_emitted = dict(data)
        self.pilotUpdated.emit(self.drone_id, data)

