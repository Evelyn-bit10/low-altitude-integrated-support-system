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
        QWidget { font-family: "Microsoft YaHei"; }
        QGroupBox { border-radius: 10px; }
        QPushButton { border-radius: 8px; }
        QLineEdit, QComboBox, QSpinBox {
            border: 1px solid #dcdfe6;
            border-radius: 8px;
            padding: 6px 10px;
            background: #ffffff;
        }
        QTableWidget { border-radius: 10px; }
        QHeaderView::section {
            background-color: #f5f7fa;
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid #ebeef5;
            font-weight: bold;
        }
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
    window.showFullScreen()
    window.activateWindow()
    window.raise_()
    sys.exit(app.exec_())