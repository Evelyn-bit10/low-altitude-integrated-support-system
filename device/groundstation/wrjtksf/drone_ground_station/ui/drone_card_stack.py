"""无人机卡片堆叠容器 - 支持左右箭头切换"""
from PyQt5.QtWidgets import QMenu
from PyQt5.QtCore import pyqtSignal
from ui.card_stack_base import CardStackBase


class DroneCardStack(CardStackBase):
    """无人机卡片堆叠容器，支持左右箭头切换"""

    # 信号：当前显示的无人机ID变化时发出
    currentDroneChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(
            title="无人机",
            empty_text="暂无无人机\n点击上方 ➕ 添加无人机",
            parent=parent
        )
        # 为了兼容性，保留原有的属性名
        self.drone_cards = self.cards
        self.drone_ids = self.card_ids

    def add_card(self, drone_id, card_widget):
        """添加无人机卡片"""
        super().add_card(drone_id, card_widget)

    def show_card_at_index(self, index):
        """显示指定索引的卡片，并发出无人机切换信号"""
        super().show_card_at_index(index)
        if 0 <= index < len(self.card_ids):
            self.currentDroneChanged.emit(self.card_ids[index])

    def show_drone_list(self):
        """显示无人机列表菜单"""
        self.show_card_list()

    def show_card_list(self):
        """显示无人机列表菜单"""
        if len(self.card_ids) == 0:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #dcdfe6;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: #ecf5ff;
                color: #409EFF;
            }
        """)

        page_start = self._current_page * self.CARDS_PER_PAGE
        page_end = page_start + self.CARDS_PER_PAGE

        for i, drone_id in enumerate(self.card_ids):
            card = self.cards[drone_id]
            drone_name = getattr(card, 'drone_name', f'无人机 {drone_id}')

            if page_start <= i < page_end:
                action_text = f"✓ {drone_name} (ID: {drone_id})"
            else:
                action_text = f"   {drone_name} (ID: {drone_id})"

            action = menu.addAction(action_text)
            action.triggered.connect(lambda _, did=drone_id: self.show_card(did))

        menu.exec_(self.list_btn.mapToGlobal(self.list_btn.rect().bottomLeft()))

    def show_drone_card(self, drone_id):
        """切换到指定无人机的卡片"""
        self.show_card(drone_id)

    def get_current_drone_id(self):
        """获取当前显示的无人机ID"""
        return self.get_current_card_id()
