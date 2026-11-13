"""通用卡片堆叠容器基类 — 每页6张卡片单列竖排布局"""
from PyQt5.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
                             QStackedWidget, QLabel, QSizePolicy, QMenu,
                             QGridLayout, QWidget, QScrollArea)
from PyQt5.QtCore import Qt, pyqtSignal


class CardStackBase(QFrame):
    """通用卡片堆叠容器基类，支持左右箭头翻页和列表快速跳转。
    
    每页显示 CARDS_PER_PAGE 张卡片（单列竖排），翻页按钮切换页。"""

    CARDS_PER_PAGE = 6
    GRID_COLS = 1

    # 信号：当前显示的卡片ID变化时发出（翻页后发出最后选中页第一张的ID）
    currentCardChanged = pyqtSignal(str)

    def __init__(self, title="卡片", empty_text="暂无数据", parent=None):
        super().__init__(parent)
        self.title = title
        self.empty_text = empty_text
        self.cards = {}  # {card_id: card_widget}
        self.card_ids = []  # 保持顺序的card_id列表
        self._current_page = 0  # 当前页码（0-based）
        self._page_widgets = []  # [(page_widget, card_ids_on_page)]
        # 优化：减少重绘，避免全屏闪烁
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setup_ui()

    def setup_ui(self):
        """初始化UI"""
        self.setStyleSheet("""
            CardStackBase {
                background-color: transparent;
                border: none;
            }
            QPushButton#navBtn {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 20px;
                font-size: 18px;
                font-weight: bold;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }
            QPushButton#navBtn:hover {
                background-color: #66b1ff;
            }
            QPushButton#navBtn:pressed {
                background-color: #3a8ee6;
            }
            QPushButton#navBtn:disabled {
                background-color: #c0c4cc;
                color: #909399;
            }
            QPushButton#listBtn {
                background-color: #67C23A;
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 14px;
                font-weight: bold;
                padding: 4px 12px;
                min-height: 32px;
            }
            QPushButton#listBtn:hover {
                background-color: #85ce61;
            }
            QPushButton#listBtn:pressed {
                background-color: #5daf34;
            }
            QLabel#counterLabel {
                font-size: 13px;
                color: #606266;
                font-weight: bold;
                background-color: #f4f4f5;
                padding: 4px 12px;
                border-radius: 12px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # 导航栏：左箭头 + 计数器 + 列表按钮 + 右箭头
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(8)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setObjectName("navBtn")
        self.prev_btn.clicked.connect(self.show_previous)
        self.prev_btn.setEnabled(False)
        nav_layout.addWidget(self.prev_btn)

        nav_layout.addStretch()

        self.counter_label = QLabel("0 / 0")
        self.counter_label.setObjectName("counterLabel")
        self.counter_label.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self.counter_label)

        # 添加列表按钮
        self.list_btn = QPushButton("📋 列表")
        self.list_btn.setObjectName("listBtn")
        self.list_btn.clicked.connect(self.show_card_list)
        self.list_btn.setEnabled(False)
        nav_layout.addWidget(self.list_btn)

        nav_layout.addStretch()

        self.next_btn = QPushButton("▶")
        self.next_btn.setObjectName("navBtn")
        self.next_btn.clicked.connect(self.show_next)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

        main_layout.addLayout(nav_layout)

        # 卡片堆叠容器（每页是多个卡片的网格）
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background-color: transparent; }")
        self.stack.setMinimumHeight(0)
        self.stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        main_layout.addWidget(self.stack, 0)

        # 空状态提示
        self.empty_page = QLabel(self.empty_text)
        self.empty_page.setAlignment(Qt.AlignCenter)
        self.empty_page.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #909399;
                padding: 40px 20px;
                background-color: #f8f9fa;
                border: 2px dashed #dcdfe6;
                border-radius: 8px;
            }
        """)
        self.stack.addWidget(self.empty_page)

        main_layout.addStretch(1)
        self.update_navigation()

    # ------------------------------------------------------------------
    # 页面构建
    # ------------------------------------------------------------------

    def _rebuild_pages(self):
        """根据 card_ids 重建所有分页。"""
        # 清除旧页面（保留 empty_page 在 index 0）
        while self.stack.count() > 1:
            w = self.stack.widget(1)
            self.stack.removeWidget(w)
            w.deleteLater()
        self._page_widgets.clear()

        total = len(self.card_ids)
        if total == 0:
            self._current_page = 0
            self.stack.setCurrentIndex(0)
            return

        per_page = self.CARDS_PER_PAGE
        page_count = (total + per_page - 1) // per_page

        for pi in range(page_count):
            start = pi * per_page
            end = min(start + per_page, total)
            page_cards = self.card_ids[start:end]

            page_widget = QWidget()
            page_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            page_layout = QVBoxLayout(page_widget)
            page_layout.setContentsMargins(2, 2, 2, 2)
            page_layout.setSpacing(6)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)

            for i, cid in enumerate(page_cards):
                row = i // self.GRID_COLS
                col = i % self.GRID_COLS
                card = self.cards[cid]
                # 压缩卡片，让它们适合网格
                card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
                card.setMinimumHeight(0)
                card.setMaximumHeight(16777215)
                grid.addWidget(card, row, col)

            # 填充空位（保持网格完整）
            remaining = per_page - len(page_cards)
            for i in range(len(page_cards), per_page):
                row = i // self.GRID_COLS
                col = i % self.GRID_COLS
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                grid.addWidget(spacer, row, col)

            # 让最后一列均匀拉伸
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

            page_layout.addLayout(grid)
            page_layout.addStretch()

            self.stack.addWidget(page_widget)
            self._page_widgets.append((page_widget, list(page_cards)))

        # 确保 current_page 在有效范围
        if self._current_page >= page_count:
            self._current_page = page_count - 1
        self.stack.setCurrentIndex(self._current_page + 1)  # +1 跳过 empty_page

    def add_card(self, card_id, card_widget):
        """添加一张卡片。"""
        if card_id in self.cards:
            return

        self.setUpdatesEnabled(False)
        card_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self.cards[card_id] = card_widget
        self.card_ids.append(card_id)

        was_empty = len(self.card_ids) == 1
        self._rebuild_pages()
        if was_empty and self._page_widgets:
            self._current_page = 0

        self.update_navigation()
        self.setUpdatesEnabled(True)

    def remove_card(self, card_id):
        """移除一张卡片。"""
        if card_id not in self.cards:
            return

        self.setUpdatesEnabled(False)

        card = self.cards[card_id]
        del self.cards[card_id]
        self.card_ids.remove(card_id)
        card.deleteLater()

        if len(self.card_ids) == 0:
            self._current_page = 0
            self._page_widgets.clear()
            self.stack.setCurrentIndex(0)
        else:
            self._rebuild_pages()

        self.update_navigation()
        self.setUpdatesEnabled(True)

    def show_next(self):
        """翻到下一页。"""
        if self._current_page < len(self._page_widgets) - 1:
            self._current_page += 1
            self.stack.setCurrentIndex(self._current_page + 1)
            self.update_navigation()
            self._emit_page_changed()

    def show_previous(self):
        """翻到上一页。"""
        if self._current_page > 0:
            self._current_page -= 1
            self.stack.setCurrentIndex(self._current_page + 1)
            self.update_navigation()
            self._emit_page_changed()

    def show_card_at_index(self, index):
        """翻到包含第 index 张卡片的页面。"""
        if not self._page_widgets:
            return
        page = index // self.CARDS_PER_PAGE
        if page >= len(self._page_widgets):
            page = len(self._page_widgets) - 1
        if page != self._current_page:
            self._current_page = page
            self.stack.setCurrentIndex(self._current_page + 1)
            self.update_navigation()
        self._emit_page_changed()

    def show_card(self, card_id):
        """翻到包含指定 card_id 的页面。"""
        if card_id in self.card_ids and self._page_widgets:
            index = self.card_ids.index(card_id)
            self.show_card_at_index(index)

    def _emit_page_changed(self):
        """翻页后发出当前页第一张卡片的信号。"""
        if self._page_widgets and 0 <= self._current_page < len(self._page_widgets):
            page_cards = self._page_widgets[self._current_page][1]
            if page_cards:
                self.currentCardChanged.emit(page_cards[0])

    def update_navigation(self):
        """更新导航按钮状态和计数器。"""
        total = len(self.card_ids)
        if total == 0:
            self.counter_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.list_btn.setEnabled(False)
        else:
            page_count = len(self._page_widgets)
            self.counter_label.setText(f"第{self._current_page + 1}/{page_count}页 共{total}张")
            self.prev_btn.setEnabled(self._current_page > 0)
            self.next_btn.setEnabled(self._current_page < page_count - 1)
            self.list_btn.setEnabled(True)

    def show_card_list(self):
        """显示卡片列表菜单 - 子类需要重写此方法。"""
        pass

    def get_current_card_id(self):
        """获取当前页的第一张卡片ID。"""
        if self._page_widgets and 0 <= self._current_page < len(self._page_widgets):
            page_cards = self._page_widgets[self._current_page][1]
            if page_cards:
                return page_cards[0]
        return None

    def get_card(self, card_id):
        """根据card_id获取卡片。"""
        return self.cards.get(card_id)
