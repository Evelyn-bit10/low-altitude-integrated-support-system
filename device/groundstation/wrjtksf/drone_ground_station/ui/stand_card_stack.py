"""机位卡片堆叠容器"""
from PyQt5.QtWidgets import QMenu
from PyQt5.QtCore import pyqtSignal
from ui.card_stack_base import CardStackBase


class StandCardStack(CardStackBase):
    """机位卡片堆叠容器"""

    # 信号
    standReleased = pyqtSignal(str)  # stand_id

    def __init__(self, parent=None):
        super().__init__(
            title="机位管理",
            empty_text="暂无机位\n请配置机位信息",
            parent=parent
        )
        self.current_assignments = {}  # drone_id -> stand_id
        self.stand_details = {}  # stand_id -> stand_info

    def show_card_list(self):
        """显示机位列表菜单"""
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
            QMenu::separator {
                height: 1px;
                background-color: #ebeef5;
                margin: 4px 0;
            }
        """)

        # 按状态分组显示
        occupied_stands = []
        free_stands = []

        for i, stand_id in enumerate(self.card_ids):
            card = self.cards[stand_id]
            stand_name = getattr(card, '_stand_name', stand_id)
            is_occupied = getattr(card, '_is_occupied', False)

            if is_occupied:
                occupied_stands.append((i, stand_id, stand_name))
            else:
                free_stands.append((i, stand_id, stand_name))

        page_start = self._current_page * self.CARDS_PER_PAGE
        page_end = page_start + self.CARDS_PER_PAGE

        # 添加已占用机位
        if occupied_stands:
            menu.addSection("🔴 已占用")
            for i, stand_id, stand_name in occupied_stands:
                if page_start <= i < page_end:
                    action_text = f"✓ {stand_name} (ID: {stand_id})"
                else:
                    action_text = f"   {stand_name} (ID: {stand_id})"
                action = menu.addAction(action_text)
                action.triggered.connect(lambda _, sid=stand_id: self.show_card(sid))

        # 添加空闲机位
        if free_stands:
            if occupied_stands:
                menu.addSeparator()
            menu.addSection("🟢 空闲")
            for i, stand_id, stand_name in free_stands:
                if page_start <= i < page_end:
                    action_text = f"✓ {stand_name} (ID: {stand_id})"
                else:
                    action_text = f"   {stand_name} (ID: {stand_id})"
                action = menu.addAction(action_text)
                action.triggered.connect(lambda _, sid=stand_id: self.show_card(sid))

        menu.exec_(self.list_btn.mapToGlobal(self.list_btn.rect().bottomLeft()))

    def update_assignments(self, assignments):
        """更新机位分配状态"""
        self.current_assignments = assignments
        # 更新卡片状态
        for stand_id, card in self.cards.items():
            # 查找占用该机位的无人机ID
            drone_id = None
            for did, stand_info in assignments.items():
                if stand_info.get("id") == stand_id:
                    drone_id = did
                    break

            # 更新卡片占用状态
            if hasattr(card, 'set_occupied'):
                card.set_occupied(drone_id)
            # 更新卡片属性供列表显示使用
            card._is_occupied = (drone_id is not None)

    def get_first_free_stand_id(self):
        """获取第一个空闲机位的ID"""
        for stand_id in self.card_ids:
            if stand_id not in self.current_assignments.values():
                return stand_id
        return None

    def show_stand_for_drone(self, drone_id):
        """显示无人机对应的机位，如果未分配则显示第一个空闲机位"""
        # 查找无人机分配的机位
        assigned_stand_id = self.current_assignments.get(drone_id)

        if assigned_stand_id and assigned_stand_id in self.card_ids:
            # 显示已分配的机位
            self.show_card(assigned_stand_id)
        else:
            # 显示第一个空闲机位
            free_stand_id = self.get_first_free_stand_id()
            if free_stand_id:
                self.show_card(free_stand_id)
