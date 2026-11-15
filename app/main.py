"""GUI 入口。"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    from .ui.theme import apply

    app = QApplication(sys.argv)
    app.setApplicationName("短剧转电影自动化平台")
    apply(app)                       # 全局深色科技主题
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
