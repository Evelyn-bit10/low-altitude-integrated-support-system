# ui/pilot_panel.py
"""【飞手信息】飞手集中管理面板：将飞手信息改为“卡片式”集中管理，外观参考 `DroneInfoCard`"""

from typing import Dict, List

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QScrollArea,
    QLabel,
)
from PyQt5.QtCore import pyqtSignal

from ui.pilot_card import PilotInfoCard


class PilotManagementPanel(QWidget):
    """【飞手信息】集中管理面板（每台无人机一张飞手信息卡片）"""

    pilotUpdated = pyqtSignal(str, dict)   # drone_id, {"name":..., "email":..., "phone":...}
    pilotViewRequested = pyqtSignal(str)  # drone_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drone_id_order: List[str] = []
        self._cards: Dict[str, PilotInfoCard] = {}
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("pilotPanel")
        self.setStyleSheet("""
            #pilotPanel {
                background-color: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 8px;
            }
        """)
#宽度
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title_icon = QLabel("👨‍✈️")
        title_icon.setStyleSheet("font-size: 15px;")
        title_row.addWidget(title_icon)

        title = QLabel("【飞手信息】双击编辑")
        title.setStyleSheet(
            "font-family: 'Microsoft YaHei', sans-serif; font-size: 16px; font-weight: bold; color:#303133; padding: 4px 0px;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #ebeef5; max-height: 1px; border: none; margin: 6px 0;")
        layout.addWidget(line)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea { background-color: transparent; border: none; }
            QScrollBar:vertical { border: none; background: #f5f7fa; width: 6px; border-radius: 3px; }
            QScrollBar::handle:vertical { background: #c0c4cc; min-height: 20px; border-radius: 3px; }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        self.cards_layout = QVBoxLayout(scroll_content)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch(1)  # 最后一个是 stretch，用于自适应底部空白

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

    def _clear_cards(self):
        """安全清理布局里的所有卡片（包含末尾 stretch spacer）。"""
        # 使用 takeAt() 循环移除，避免直接对 stretch spacer 的 removeItem() 引发 Qt 崩溃
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._cards.clear()
        self._drone_id_order.clear()
        # 重新添加底部 stretch，用于自适应空白区域
        self.cards_layout.addStretch(1)

    def _create_card(self, drone_id: str, drone_name: str, pilot: dict) -> PilotInfoCard:
        card = PilotInfoCard(drone_id=drone_id, drone_name=drone_name, pilot=pilot, parent=self)
        card.pilotUpdated.connect(lambda did, data: self.pilotUpdated.emit(did, data))
        card.pilotViewRequested.connect(lambda did: self.pilotViewRequested.emit(did))
        return card

    def _add_card_to_layout(self, card: PilotInfoCard):
        # 假设最后一个 item 是 stretch：插入到 stretch 前
        insert_at = max(0, self.cards_layout.count() - 1)
        self.cards_layout.insertWidget(insert_at, card)

    def set_data(self, drones: list, pilots: dict):
        """【飞手信息】用整表数据刷新。drones: DEFAULT_DRONES/已添加无人机列表; pilots: {id: {name,email,phone}}"""
        self._clear_cards()
        pilots = pilots or {}

        for d in drones:
            drone_id = str(d.get("id"))
            drone_name = d.get("name", f"无人机 {drone_id}")
            p = pilots.get(drone_id, {}) or {}

            card = self._create_card(drone_id, drone_name, p)
            self._cards[drone_id] = card
            self._drone_id_order.append(drone_id)
            self._add_card_to_layout(card)

    def upsert_row(self, drone_id: str, drone_name: str, pilot: dict):
        """【飞手信息】单条更新/插入某台无人机飞手信息"""
        drone_id = str(drone_id)
        pilot = pilot or {}

        if drone_id in self._cards:
            card = self._cards[drone_id]
            # 更新标题（无人机名称可能变更）
            card.set_drone_name(drone_name)
            card.set_pilot(
                name=pilot.get("name", ""),
                email=pilot.get("email", ""),
                phone=pilot.get("phone", ""),
            )
            return

        # 新增卡片：保持和首次 set_data 一致的插入顺序
        card = self._create_card(drone_id, drone_name, pilot)
        self._cards[drone_id] = card
        self._drone_id_order.append(drone_id)
        self._add_card_to_layout(card)