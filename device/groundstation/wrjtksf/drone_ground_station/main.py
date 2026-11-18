import sys

from PyQt5.QtWidgets import QApplication,QShortcut
from PyQt5.QtGui import QKeySequence, QFont
import PyQt5.QtCore
from ui.main_window import MapWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # 使用 Fusion 样式可减少 Windows 下原生样式切换导致的整窗闪烁
    app.setStyle("Fusion")
    # 全局统一字体（避免各处 setStyleSheet 中字体不一致）
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet("""
        /* ---------- 全局基础 ---------- */
        QWidget {
            font-family: "Microsoft YaHei UI", "Microsoft YaHei";
            font-size: 10pt;
        }
        QMainWindow, QWidget#mainCentralWidget { background: #f4f7fb; }

        /* ---------- 分组框 ---------- */
        QGroupBox {
            border: 1px solid #dfe7f1;
            border-radius: 10px;
            margin-top: 10px;
            padding-top: 8px;
            background: #ffffff;
            font-weight: 600;
            color: #1f3a5f;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #1f5fa8;
        }

        /* ---------- 按钮 ---------- */
        QPushButton {
            min-height: 30px;
            padding: 4px 14px;
            border-radius: 8px;
            border: 1px solid #c6d8ef;
            background: #ffffff;
            color: #1f4e79;
        }
        QPushButton:hover { background: #eaf4ff; border-color: #6fb3ff; }
        QPushButton:pressed { background: #d8ecff; }
        QPushButton:disabled { color: #9aa9bb; background: #f3f6fa; border-color: #e2e9f2; }

        /* ---------- 输入 ---------- */
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            min-height: 28px;
            padding: 3px 10px;
            border: 1px solid #d6e2f0;
            border-radius: 8px;
            background: #ffffff;
            selection-background-color: #409eff;
            selection-color: #ffffff;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
            border-color: #409eff;
        }
        QComboBox::drop-down { border: none; width: 22px; }

        /* ---------- 表格 ---------- */
        QTableWidget {
            border: 1px solid #e3ebf5;
            border-radius: 10px;
            gridline-color: #eef3fa;
            background: #ffffff;
            alternate-background-color: #f8fbff;
            selection-background-color: #e6f2ff;
            selection-color: #1f3a5f;
        }
        QHeaderView::section {
            background: #f2f7fe;
            color: #4a6b8f;
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid #e3ebf5;
            font-weight: 600;
        }

        /* ---------- 标签页 ---------- */
        QTabWidget::pane {
            border: 1px solid #e3ebf5;
            border-radius: 10px;
            background: #ffffff;
        }
        QTabBar::tab {
            background: #eef4fb;
            color: #5a7391;
            padding: 6px 14px;
            border: 1px solid #e3ebf5;
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 2px;
        }
        QTabBar::tab:selected { background: #ffffff; color: #1f5fa8; border-color: #cfe1f6; }
        QTabBar::tab:hover { background: #e6f1ff; }

        /* ---------- 滚动条 ---------- */
        QScrollBar:vertical { width: 10px; background: transparent; margin: 2px; }
        QScrollBar::handle:vertical { background: #c8d7e8; border-radius: 5px; min-height: 30px; }
        QScrollBar::handle:vertical:hover { background: #9fc2e8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { height: 10px; background: transparent; margin: 2px; }
        QScrollBar::handle:horizontal { background: #c8d7e8; border-radius: 5px; min-width: 30px; }
        QScrollBar::handle:horizontal:hover { background: #9fc2e8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

        /* ---------- 分割条 / 提示 ---------- */
        QSplitter::handle { background: #e8eff8; }
        QSplitter::handle:hover { background: #bcd8f5; }
        QToolTip {
            background: #1f3a5f;
            color: #ffffff;
            border: none;
            padding: 4px 8px;
            border-radius: 6px;
        }
        QTextEdit, QPlainTextEdit {
            border: 1px solid #e3ebf5;
            border-radius: 8px;
            background: #ffffff;
        }
        QCheckBox, QRadioButton { spacing: 6px; color: #33475f; }
    """)
    
    window = MapWindow()
    window.shortcut = QShortcut(QKeySequence("Esc"),window)
    window.shortcut.setContext(PyQt5.QtCore.Qt.ApplicationShortcut)
    def toggle_fullscreen():
        # Esc：未全屏 -> 全屏；全屏 -> 退出全屏
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()
        window.activateWindow()
        window.raise_()

    window.shortcut.activated.connect(toggle_fullscreen)
    window.showMaximized()
    window.activateWindow()
    window.raise_()
    sys.exit(app.exec_())