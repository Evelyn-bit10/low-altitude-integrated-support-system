"""飞手信息编辑（校验逻辑对齐 drone_ground_station）。"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)


class PilotInfoDialog(QDialog):
    def __init__(
        self,
        pilot_name: str = "",
        pilot_email: str = "",
        pilot_phone: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("飞手信息")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.current_drone_id: Optional[str] = None
        self._build_ui(pilot_name, pilot_email, pilot_phone)

    def _build_ui(self, name: str, email: str, phone: str) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(name or "")
        self.email_edit = QLineEdit(email or "")
        self.phone_edit = QLineEdit(phone or "")
        self.email_edit.setPlaceholderText("example@domain.com")
        self.phone_edit.setPlaceholderText("11 位手机号")
        form.addRow("飞手姓名:", self.name_edit)
        form.addRow("飞手邮箱:", self.email_edit)
        form.addRow("飞手电话:", self.phone_edit)
        layout.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._try_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self) -> dict[str, str]:
        return {
            "name": self.name_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
        }

    def _try_accept(self) -> None:
        values = self.get_values()
        email = values.get("email", "").strip()
        phone = values.get("phone", "").strip()
        name = values.get("name", "").strip()

        if email and not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
            QMessageBox.warning(self, "格式错误", "请输入有效的邮箱地址。\n例如：example@domain.com")
            return
        if phone and not re.match(r"^1[3-9]\d{9}$", phone):
            QMessageBox.warning(self, "格式错误", "请输入有效的 11 位手机号码。")
            return

        parent = self.parent()
        current_id = self.current_drone_id
        if parent is not None and current_id is not None:
            pilots = getattr(parent, "drone_pilots", None)
            if pilots is None:
                pilots = getattr(parent, "_drone_pilots", {})
            cards = getattr(parent, "drone_cards", None)
            if cards is None:
                cards = getattr(parent, "_drone_cards", {})

            for other_id, info in pilots.items():
                if str(other_id) == str(current_id):
                    continue
                oname = (info or {}).get("name", "")
                oemail = (info or {}).get("email", "")
                ophone = (info or {}).get("phone", "")
                other_drone_name = f"无人机 {other_id}"
                oc = cards.get(str(other_id))
                if oc is not None and getattr(oc, "drone_name", None):
                    other_drone_name = oc.drone_name
                if name and name == oname:
                    QMessageBox.warning(
                        self,
                        "信息冲突",
                        f"该姓名已被【{other_drone_name}】的飞手使用。\n请使用其他姓名以作区分。",
                    )
                    return
                if email and email == oemail:
                    QMessageBox.warning(
                        self,
                        "信息冲突",
                        f"该邮箱已被【{other_drone_name}】使用。\n请更换其他邮箱。",
                    )
                    return
                if phone and phone == ophone:
                    QMessageBox.warning(
                        self,
                        "信息冲突",
                        f"该手机号已被【{other_drone_name}】使用。\n请更换其他手机号。",
                    )
                    return

        self.accept()
