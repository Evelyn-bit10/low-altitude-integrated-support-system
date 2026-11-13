# ui/stand_management_panel.py
"""机位管理面板（卡片式展示）"""
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QFrame,
    QScrollArea,
    QWidget,
    QMessageBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDialogButtonBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtCore import QTimer

from typing import Dict, List, Optional
from datetime import datetime

from utils.stand_store import (
    list_stands,
    add_or_update_custom_stand,
    delete_custom_stand,
    is_default_stand,
    mark_deleted,
)
from ui.stand_card import StandInfoCard


class StandManagementPanel(QGroupBox):
    """机位管理面板"""
    
    standReleased = pyqtSignal(str)  # 机位ID

    def __init__(self, parent=None):
        super().__init__("机位管理(空闲/总数)", parent)
        self.current_assignments = {}  # 无人机ID -> 机位ID
        self.stand_details = {}  # 机位ID -> 详细信息
        self.setup_ui()
        
    def setup_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        # 统一机位面板整体观感
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #dcdfe6;
                border-radius: 10px;
                background: transparent;
                margin-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #303133;
                font-weight: bold;
            }
        """)
        
        # 状态统计
        self.stats_label = QLabel("室内机位: 0/0 | 室外机位: 0/0 | 总计: 0/0")
        self.stats_label.setStyleSheet("""
            QLabel {
                padding: 6px;
                background-color: #f5f7fa;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.stats_label)
        
        # 机位卡片列表
        self._cards_container = QScrollArea()
        self._cards_container.setWidgetResizable(True)
        self._cards_container.setFrameShape(QFrame.NoFrame)
        self._cards_container.setStyleSheet("""
            QScrollArea { background-color: transparent; border: none; }
            QScrollBar:vertical { border: none; background: #f5f7fa; width: 6px; border-radius: 3px; }
            QScrollBar::handle:vertical { background: #c0c4cc; min-height: 20px; border-radius: 3px; }
        """)

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background-color: transparent;")
        self._cards_layout = QVBoxLayout(self._scroll_content)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch(1)

        self._cards_container.setWidget(self._scroll_content)
        layout.addWidget(self._cards_container)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ 添加机位")
        add_btn.clicked.connect(self._open_add_stand_dialog)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #67C23A;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #85ce61; }
        """)
        btn_layout.addWidget(add_btn)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh_display)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #409EFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #66b1ff;
            }
        """)
        btn_layout.addWidget(refresh_btn)
        
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        self.load_stands()
        
    def load_stands(self):
        """加载机位数据"""
        stands = list_stands()
        self.stand_details = {stand["id"]: stand for stand in stands if isinstance(stand, dict) and stand.get("id")}
        self._cards: Dict[str, StandInfoCard] = {}

        # 清空旧卡片（用 takeAt 更安全：同时处理 widget item 和 spacer item）
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if not item:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            # spacer item 无需额外处理，交给 Python/Qt 回收
        self._cards_layout.addStretch(1)

        # 创建全部机位卡片（后续 refresh 只更新占用状态）
        for stand_id, stand in self.stand_details.items():
            card = StandInfoCard(
                stand_id=stand_id,
                name=stand.get("name", stand_id),
                stand_type=stand.get("type", "outdoor"),
                # 关键：卡片必须属于 scroll_content，否则重建/滚动时容易出现 Qt 崩溃退出
                parent=self._scroll_content,
            )
            card.releaseStandClicked.connect(self.release_stand)
            card.deleteStandClicked.connect(self._on_delete_stand_clicked)
            card.editStandClicked.connect(self._on_edit_stand_clicked)
            # 插入到 stretch 前面
            insert_at = max(0, self._cards_layout.count() - 1)
            self._cards_layout.insertWidget(insert_at, card)
            self._cards[str(stand_id)] = card

        self.refresh_display()
        
# ui/stand_management_panel.py (修改 refresh_display 方法)

    def refresh_display(self):
        """刷新显示"""
        # 更新统计数据
        total_stands = len(self.stand_details)
        indoor_stands = sum(1 for s in self.stand_details.values() if s["type"] == "indoor")
        outdoor_stands = total_stands - indoor_stands
        
        occupied_indoor = 0
        occupied_outdoor = 0
        
        # 重新统计占用情况
        for drone_id, stand_id in self.current_assignments.items():
            stand_type = self.stand_details.get(stand_id, {}).get("type", "outdoor")
            if stand_type == "indoor":
                occupied_indoor += 1
            else:
                occupied_outdoor += 1
        
        # 改为显示“空闲机位 / 总机位”
        free_indoor = max(0, indoor_stands - occupied_indoor)
        free_outdoor = max(0, outdoor_stands - occupied_outdoor)
        free_total = max(0, total_stands - len(self.current_assignments))

        self.stats_label.setText(
            f"🏠 室内: {free_indoor}/{indoor_stands}| "
            f"🌳 室外: {free_outdoor}/{outdoor_stands}| "
            f"📊 总计: {free_total}/{total_stands}"
        )
        
        # 反查：stand_id -> drone_id
        stand_to_drone: Dict[str, str] = {str(s_id): str(d_id) for d_id, s_id in self.current_assignments.items()}

        for stand_id in self.stand_details.keys():
            card = self._cards.get(str(stand_id))
            if not card:
                continue
            occupied_drone: Optional[str] = stand_to_drone.get(str(stand_id))
            card.set_occupied(occupied_drone)
    # ui/stand_management_panel.py (添加新方法)

    def remove_assignment(self, drone_id):
        """移除无人机的机位分配"""
        if drone_id in self.current_assignments:
            del self.current_assignments[drone_id]
            self.refresh_display()
            return True
        return False
    
    def assign_stand(self, drone_id: str, stand: dict):
        """分配机位"""
        # 如果无人机已有分配，先释放
        if drone_id in self.current_assignments:
            old_stand = self.current_assignments[drone_id]
            self.current_assignments.pop(drone_id)
            
        # 分配新机位
        self.current_assignments[drone_id] = stand["id"]
        # 分配时可能带入 assigned_time/drone_id 字段，这里保留原始 stand 配置字段
        sid = stand.get("id")
        if sid:
            # 如果存储中已有该机位配置，以存储为准；否则用传入的 stand 做兜底
            self.stand_details[str(sid)] = self.stand_details.get(str(sid), stand)
        
        self.refresh_display()
        
    def release_stand(self, stand_id: str):
        """释放机位"""
        stand_id = str(stand_id)
        drone_id = None
        for d_id, s_id in self.current_assignments.items():
            if str(s_id) == stand_id:
                drone_id = d_id
                break
                
        if drone_id:
            msg = QMessageBox(self)
            msg.setWindowTitle("确认释放")
            msg.setText(f"确定要释放机位 {stand_id} (无人机 {drone_id}) 吗？")
            msg.setIcon(QMessageBox.Question)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            yes_btn = msg.button(QMessageBox.Yes)
            no_btn = msg.button(QMessageBox.No)
            if yes_btn:
                yes_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #409EFF;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #66b1ff; }
                """)
            if no_btn:
                no_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #909399;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #a6a9ad; }
                """)
            reply = msg.exec_()
            
            if reply == QMessageBox.Yes:
                self.current_assignments.pop(drone_id)
                self.refresh_display()
                self.standReleased.emit(stand_id)
                
    def get_stand_for_drone(self, drone_id: str) -> str:
        """获取无人机分配的机位"""
        return self.current_assignments.get(drone_id)
        
    def get_occupied_stands(self) -> List[str]:
        """获取所有已占用的机位ID"""
        return list(self.current_assignments.values())

    # ==================== 新增：添加/删除机位 ====================
    def _open_add_stand_dialog(self):
        try:
            dlg = _AddStandDialog(parent=self)
            result = dlg.exec_()
            if result == QDialog.Accepted:
                stand = dlg.get_values()
                add_or_update_custom_stand(stand)
                # 避免在按钮回调中立即重建布局造成 Qt 重入问题
                QTimer.singleShot(0, self.load_stands)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加机位发生异常：{e}")

    def _on_edit_stand_clicked(self, stand_id: str):
        try:
            stand_id = str(stand_id)
            stand = self.stand_details.get(stand_id) or {}
            dlg = _AddStandDialog(parent=self, initial=stand)
            dlg.setWindowTitle("编辑机位")
            result = dlg.exec_()
            if result == QDialog.Accepted:
                values = dlg.get_values()
                add_or_update_custom_stand(values)  # 覆盖默认 or 更新自定义
                QTimer.singleShot(0, self.load_stands)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"编辑机位发生异常：{e}")

    def _on_delete_stand_clicked(self, stand_id: str):
        try:
            stand_id = str(stand_id)
            # 占用中不允许删除（卡片也会 disable，但这里再兜底）
            if stand_id in set(str(x) for x in self.current_assignments.values()):
                QMessageBox.warning(self, "无法删除", "该机位正在被占用，无法删除。")
                return

            msg = QMessageBox(self)
            msg.setWindowTitle("确认删除机位")
            if is_default_stand(stand_id):
                msg.setText(f"确定要删除默认机位 {stand_id} 吗？\n\n将从界面与分配列表中隐藏该默认机位。")
            else:
                msg.setText(f"确定要删除机位 {stand_id} 吗？\n\n仅会删除自定义机位配置。")
            msg.setIcon(QMessageBox.Question)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            # 美化 Yes/No（与全局弹窗风格一致）
            yes_btn = msg.button(QMessageBox.Yes)
            no_btn = msg.button(QMessageBox.No)
            if yes_btn:
                yes_btn.setText("确定")
                yes_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #409EFF;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #66b1ff; }
                    QPushButton:pressed { background-color: #3a8ee6; }
                """)
            if no_btn:
                no_btn.setText("取消")
                no_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #909399;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 6px 16px;
                        font-weight: bold;
                        min-height: 26px;
                    }
                    QPushButton:hover { background-color: #a6a9ad; }
                    QPushButton:pressed { background-color: #848688; }
                """)
            reply = msg.exec_()
            if reply != QMessageBox.Yes:
                return

            if is_default_stand(stand_id):
                mark_deleted(stand_id)
            else:
                deleted = delete_custom_stand(stand_id)
                if not deleted:
                    QMessageBox.information(self, "提示", "未找到对应的自定义机位，可能已被删除。")
            QTimer.singleShot(0, self.load_stands)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除机位发生异常：{e}")


class _AddStandDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[Dict[str, object]] = None):
        super().__init__(parent)
        self.setWindowTitle("添加机位")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("例如：custom_01（建议唯一）")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：自定义机位 1")

        self.type_combo = QComboBox()
        self.type_combo.addItems(["indoor", "outdoor"])

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 999)
        self.priority_spin.setValue(1)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("可选：机位描述")

        # features（简单勾选）
        self.feature_rain = QCheckBox("rain_proof")
        self.feature_wind = QCheckBox("wind_proof")
        self.feature_normal = QCheckBox("normal")
        feature_wrap = QWidget()
        feature_row = QHBoxLayout(feature_wrap)
        feature_row.setContentsMargins(0, 0, 0, 0)
        feature_row.setSpacing(10)
        feature_row.addWidget(self.feature_rain)
        feature_row.addWidget(self.feature_wind)
        feature_row.addWidget(self.feature_normal)
        feature_row.addStretch(1)

        form.addRow("机位ID*", self.id_edit)
        form.addRow("名称*", self.name_edit)
        form.addRow("类型", self.type_combo)
        form.addRow("优先级", self.priority_spin)
        form.addRow("描述", self.desc_edit)
        form.addRow("特性", feature_wrap)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        # 美化 OK / Cancel 按钮（与 dialogs.py 风格一致）
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setText("确定")
            ok_btn.setStyleSheet("""
                QPushButton {
                    background-color: #409EFF;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                    min-height: 26px;
                }
                QPushButton:hover { background-color: #66b1ff; }
                QPushButton:pressed { background-color: #3a8ee6; }
            """)
        if cancel_btn:
            cancel_btn.setText("取消")
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #909399;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 6px 16px;
                    font-weight: bold;
                    min-height: 26px;
                }
                QPushButton:hover { background-color: #a6a9ad; }
                QPushButton:pressed { background-color: #848688; }
            """)
        buttons.setStyleSheet("QDialogButtonBox QPushButton{ min-height: 28px; }")
        layout.addWidget(buttons)

        # 初始值（用于编辑）
        if initial:
            try:
                self.id_edit.setText(str(initial.get("id", "") or ""))
                # 编辑默认/自定义都要求 id 不变：禁用 id 编辑避免产生“复制”
                self.id_edit.setEnabled(False)
                self.name_edit.setText(str(initial.get("name", "") or ""))
                st = str(initial.get("type", "outdoor") or "outdoor")
                self.type_combo.setCurrentText(st if st in ("indoor", "outdoor") else "outdoor")
                self.priority_spin.setValue(int(initial.get("priority", 1) or 1))
                self.desc_edit.setText(str(initial.get("description", "") or ""))
                feats = initial.get("features") or []
                if isinstance(feats, list):
                    self.feature_rain.setChecked("rain_proof" in feats)
                    self.feature_wind.setChecked("wind_proof" in feats)
                    self.feature_normal.setChecked("normal" in feats)
            except Exception:
                pass

    def _validate_and_accept(self):
        stand_id = (self.id_edit.text() or "").strip()
        name = (self.name_edit.text() or "").strip()
        if not stand_id:
            QMessageBox.warning(self, "校验失败", "机位ID不能为空")
            return
        if not name:
            QMessageBox.warning(self, "校验失败", "名称不能为空")
            return
        self.accept()

    def get_values(self) -> Dict[str, object]:
        features: List[str] = []
        if self.feature_rain.isChecked():
            features.append("rain_proof")
        if self.feature_wind.isChecked():
            features.append("wind_proof")
        if self.feature_normal.isChecked():
            features.append("normal")
        return {
            "id": (self.id_edit.text() or "").strip(),
            "name": (self.name_edit.text() or "").strip(),
            "type": self.type_combo.currentText(),
            "priority": int(self.priority_spin.value()),
            "description": (self.desc_edit.text() or "").strip(),
            "features": features,
        }