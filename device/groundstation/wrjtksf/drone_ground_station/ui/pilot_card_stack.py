"""飞手信息卡片堆叠容器"""
from PyQt5.QtWidgets import QMenu
from PyQt5.QtCore import pyqtSignal
from ui.card_stack_base import CardStackBase


class PilotCardStack(CardStackBase):
    """飞手信息卡片堆叠容器"""

    # 信号
    pilotUpdated = pyqtSignal(str, dict)  # drone_id, pilot_info
    pilotViewRequested = pyqtSignal(str)  # drone_id

    def __init__(self, parent=None):
        super().__init__(
            title="飞手信息",
            empty_text="暂无飞手信息\n添加无人机后自动显示",
            parent=parent
        )

    def show_card_list(self):
        """显示飞手列表菜单"""
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
            # 获取飞手姓名和无人机名称
            pilot_name = getattr(card, '_pilot_name', '未设置')
            drone_name = getattr(card, '_drone_name', f'无人机 {drone_id}')

            if page_start <= i < page_end:
                action_text = f"✓ {drone_name} - {pilot_name}"
            else:
                action_text = f"   {drone_name} - {pilot_name}"

            action = menu.addAction(action_text)
            action.triggered.connect(lambda _, did=drone_id: self.show_card(did))

        menu.exec_(self.list_btn.mapToGlobal(self.list_btn.rect().bottomLeft()))

    def upsert_row(self, drone_id, drone_name, pilot):
        """添加或更新飞手卡片"""
        from ui.pilot_card import PilotInfoCard

        if drone_id in self.cards:
            # 更新现有卡片
            card = self.cards[drone_id]
            # 使用 set_pilot 方法更新飞手信息
            card.set_pilot(
                pilot.get('name', '') if pilot else '',
                pilot.get('email', '') if pilot else '',
                pilot.get('phone', '') if pilot else ''
            )
            # 更新属性
            card._pilot_name = pilot.get('name', '未设置') if pilot else '未设置'
            card._drone_name = drone_name
        else:
            # 创建新卡片
            card = PilotInfoCard(drone_id, drone_name, pilot)
            # 连接信号 - 使用正确的信号名称
            card.pilotUpdated.connect(lambda did, p: self.pilotUpdated.emit(did, p))
            card.pilotViewRequested.connect(lambda did: self.pilotViewRequested.emit(did))
            # 设置属性供列表显示使用
            card._pilot_name = pilot.get('name', '未设置') if pilot else '未设置'
            card._drone_name = drone_name
            self.add_card(drone_id, card)

    def remove_row(self, drone_id):
        """移除飞手卡片"""
        self.remove_card(drone_id)

    def refresh_all(self, drone_pilots_dict):
        """刷新所有飞手卡片"""
        # 清空现有卡片
        for drone_id in list(self.cards.keys()):
            self.remove_card(drone_id)

        # 重新添加
        for drone_id, info in drone_pilots_dict.items():
            self.upsert_row(
                drone_id=drone_id,
                drone_name=info.get('drone_name', f'无人机 {drone_id}'),
                pilot=info.get('pilot', {})
            )
