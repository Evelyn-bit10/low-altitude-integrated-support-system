"""添加实机：MAVLink 连接与飞手信息。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


def _enumerate_serial_ports() -> List[str]:
    """枚举本机可用串口列表。"""
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


class AddRealDroneDialog(QDialog):
    def __init__(self, *, suggested_id: str = "REAL-1", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加实机（MAVLink）")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.id_edit = QLineEdit(suggested_id)
        self.name_edit = QLineEdit(suggested_id)

        # 串口选择：下拉框 + 刷新按钮
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)  # 允许手动输入（如 udp: 地址）
        self.port_combo.setMinimumWidth(200)
        self._populate_ports()
        port_row.addWidget(self.port_combo, 1)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setToolTip("重新枚举本机串口")
        btn_refresh.clicked.connect(self._populate_ports)
        port_row.addWidget(btn_refresh)
        form.addRow("MAVLink 连接:", port_row)
        hint = QLabel("下拉选择串口，或直接输入（如 COM3 / udp:127.0.0.1:14550）")
        hint.setStyleSheet("color:#909399;font-size:11px;")
        form.addRow("", hint)

        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1200, 921600)
        self.baud_spin.setValue(57600)
        self.baud_spin.setSingleStep(1200)
        form.addRow("波特率:", self.baud_spin)
        form.addRow("无人机 ID:", self.id_edit)
        form.addRow("显示名称:", self.name_edit)
        self.pilot_name = QLineEdit()
        self.pilot_email = QLineEdit()
        self.pilot_phone = QLineEdit()
        form.addRow("飞手姓名:", self.pilot_name)
        form.addRow("飞手邮箱:", self.pilot_email)
        form.addRow("飞手电话:", self.pilot_phone)
        self.auto_connect = QCheckBox("添加后自动连接 MAVLink")
        self.auto_connect.setChecked(False)
        form.addRow("", self.auto_connect)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _populate_ports(self) -> None:
        """刷新串口下拉列表。"""
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        self.port_combo.addItem("无")
        ports = _enumerate_serial_ports()
        for p in ports:
            if self.port_combo.findText(p) == -1:
                self.port_combo.addItem(p)
        if not ports:
            self.port_combo.addItem("（未检测到串口）")
        # 恢复之前的选择
        if current:
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def get_config(self) -> Dict[str, Any]:
        did = self.id_edit.text().strip()
        port_text = self.port_combo.currentText().strip()
        if port_text == "无" or port_text.startswith("（"):
            port_text = ""
        return {
            "id": did,
            "name": self.name_edit.text().strip() or did,
            "emoji": "📡",
            "model": "MAVLink",
            "port": port_text,
            "baud": int(self.baud_spin.value()),
            "pilot": {
                "name": self.pilot_name.text().strip(),
                "email": self.pilot_email.text().strip(),
                "phone": self.pilot_phone.text().strip(),
            },
            "auto_connect": self.auto_connect.isChecked(),
        }
