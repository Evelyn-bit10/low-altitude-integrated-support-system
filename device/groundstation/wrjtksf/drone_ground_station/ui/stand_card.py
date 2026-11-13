"""机位卡片UI组件（用于机位管理面板的卡片式展示）"""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton


class StandInfoCard(QFrame):
    releaseStandClicked = pyqtSignal(str)  # stand_id
    deleteStandClicked = pyqtSignal(str)   # stand_id
    editStandClicked = pyqtSignal(str)     # stand_id

    def __init__(self, stand_id: str, name: str, stand_type: str, parent=None):
        super().__init__(parent)
        self.stand_id = str(stand_id)
        self.name = name
        self.stand_type = stand_type  # "indoor" / "outdoor"
        self.occupied_drone_id: Optional[str] = None

        self._build_ui()
        self._apply_static_content()
        self.set_occupied(None)

    def _build_ui(self):
        self.setObjectName("standInfoCard")
        self.setStyleSheet("""
            #standInfoCard {
                background-color: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 8px;
            }
            #standInfoCard[occupied="true"] {
                border: 2px solid #F56C6C;
            }
            QLabel { font-family: 'Microsoft YaHei', sans-serif; }
            QLabel#titleLabel {
                font-size: 14px;
                font-weight: bold;
                color: #303133;
                padding: 2px 0;
            }
            QLabel#typeTag {
                font-size: 12px;
                color: #67C23A;
                background-color: #f0f9eb;
                padding: 4px 10px;
                border-radius: 999px;
                font-weight: bold;
            }
            QLabel#typeTag[type="indoor"] {
                background-color: #e1f5fe;
                color: #0288d1;
            }
            QLabel#typeTag[type="outdoor"] {
                background-color: #e8f5e8;
                color: #2e7d32;
            }
            QLabel#statusLabel {
                font-size: 12px;
                font-weight: bold;
                padding: 4px 10px;
                border-radius: 999px;
            }
            QLabel#droneValueLabel {
                font-size: 13px;
                color: #606266;
            }
            QPushButton#releaseBtn {
                background-color: #F56C6C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton#releaseBtn:disabled {
                background-color: #f5f7fa;
                color: #909399;
            }
            QPushButton#releaseBtn:hover:!disabled {
                background-color: #f78989;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(8, 7, 8, 7)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        stand_icon = QLabel("📍")
        stand_icon.setStyleSheet("font-size: 14px;")
        title_row.addWidget(stand_icon)

        title = QLabel("")
        title.setObjectName("titleLabel")
        title_row.addWidget(title, 1)
        self._title_label = title

        self._type_tag = QLabel("")
        self._type_tag.setObjectName("typeTag")
        self._type_tag.setProperty("type", self.stand_type)
        title_row.addWidget(self._type_tag)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #f56c6c;
                font-size: 16px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #fef0f0; }
        """)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        title_row.addWidget(self._delete_btn)

        layout.addLayout(title_row)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        meta_row.addWidget(self._status_label, 1)

        self._drone_value_label = QLabel("--")
        self._drone_value_label.setObjectName("droneValueLabel")
        self._drone_value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        meta_row.addWidget(self._drone_value_label, 2)

        layout.addLayout(meta_row)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)

        self._edit_btn = QPushButton("编辑")
        self._edit_btn.setObjectName("releaseBtn")
        self._edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton:hover { background-color: #66b1ff; }
        """)
        self._edit_btn.clicked.connect(self._on_edit_clicked)

        self._release_btn = QPushButton("释放机位")
        self._release_btn.setObjectName("releaseBtn")
        self._release_btn.clicked.connect(self._on_release_clicked)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self._edit_btn)
        bottom_row.addWidget(self._release_btn)

        layout.addLayout(bottom_row)

    def _apply_static_content(self):
        self._title_label.setText(f"{self.name}（{self.stand_id}）")
        # stand_type 决定 tag 配色
        self._type_tag.setText("室内" if self.stand_type == "indoor" else "室外")
        self._type_tag.setProperty("type", self.stand_type)

    def set_occupied(self, drone_id: Optional[str]):
        self.occupied_drone_id = str(drone_id) if drone_id else None
        if self.occupied_drone_id:
            # 占用时整卡红色边框高亮
            self.setProperty("occupied", True)
            self._status_label.setText("🔴 已占用")
            self._status_label.setStyleSheet("background-color: rgba(245,108,108,0.12); color: #F56C6C;")
            self._drone_value_label.setText(f"占用无人机：无人机 {self.occupied_drone_id}")
            self._release_btn.setEnabled(True)
            # 🚀 核心修改：删除了禁用删除按钮的代码，允许点击并触发拦截弹窗
        else:
            # 空闲时恢复默认边框
            self.setProperty("occupied", False)
            self._status_label.setText("🟢 空闲")
            self._status_label.setStyleSheet("background-color: rgba(103,194,35,0.12); color: #67C23A;")
            self._drone_value_label.setText("--")
            self._release_btn.setEnabled(False)
            
        self.style().polish(self)

    def _on_delete_clicked(self):
        """删除按钮点击处理"""
        self.deleteStandClicked.emit(self.stand_id)

    def _on_edit_clicked(self):
        """编辑按钮点击处理"""
        self.editStandClicked.emit(self.stand_id)

    def _on_release_clicked(self):
        """释放按钮点击处理"""
        self.releaseStandClicked.emit(self.stand_id)

