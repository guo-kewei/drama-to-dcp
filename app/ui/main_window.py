"""主窗口：侧边栏导航（新建转换 / 任务队列 / 设置）+ 队列调度。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..core.config import PROJECT_ROOT, load_settings
from .compliance_page import CompliancePage
from .new_task_page import NewTaskPage
from .queue_page import TaskCard
from .settings_page import SettingsPage

#: 侧栏导航项：(图标字符, 标题, 页索引)
_NAV = [("＋", "新建转换", 0), ("≡", "任务队列", 1),
        ("⚖", "备案工作台", 2), ("⚙", "设  置", 3)]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self._cards: list[TaskCard] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setWindowTitle("短剧转电影自动化平台 — 批量 DCP 转制")
        self.resize(1160, 840)
        self.statusBar().showMessage("就绪")

        root = QFrame(objectName="root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(root)

        # ---- 侧栏
        side = QFrame(objectName="sidebar")
        side.setFixedWidth(212)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 18, 0, 12)
        sv.setSpacing(2)

        # Logo
        logo_row = QHBoxLayout()
        ico = QLabel()
        p = PROJECT_ROOT / "app.ico"
        if p.is_file():
            pm = QPixmap(str(p)).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            ico.setPixmap(pm)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        tcol.addWidget(QLabel("短剧转电影", objectName="logoName"))
        tcol.addWidget(QLabel("DRAMA · DCP STUDIO", objectName="logoSub"))
        logo_row.addWidget(ico)
        logo_row.addSpacing(8)
        logo_row.addLayout(tcol)
        logo_row.addStretch(1)
        sv.addLayout(logo_row)
        sv.addSpacing(18)

        # 导航
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for glyph, title, idx in _NAV:
            b = QPushButton(f"  {glyph}   {title}")
            b.setObjectName("navBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=idx: self.stack.setCurrentIndex(i))
            self._nav_group.addButton(b, idx)
            sv.addWidget(b)
        sv.addStretch(1)
        sv.addWidget(QLabel(f"v{__version__}\nFFmpeg + DCP-o-matic\n开源免费工具链",
                            objectName="sideFooter"))
        lay.addWidget(side)

        # ---- 页面栈
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.page_new = NewTaskPage(self.settings)
        self.page_new.task_created.connect(self.add_task)
        self.stack.addWidget(self._wrap_header(
            self.page_new, "新建转换", "选择短剧文件夹，一键转制为影院可放映的 DCP"))

        # 任务队列（滚动容器）
        queue_inner = QWidget()
        vq = QVBoxLayout(queue_inner)
        self.queue_host = QWidget()
        self.queue_lay = QVBoxLayout(self.queue_host)
        self.queue_lay.setAlignment(Qt.AlignTop)
        self.queue_lay.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.queue_host)
        vq.addWidget(scroll)
        self.stack.addWidget(self._wrap_header(
            queue_inner, "任务队列", "查看进度 · 取消 / 重试 · 打开输出目录 · 日志"))

        self.page_compliance = CompliancePage(self.settings)
        self.stack.addWidget(self._wrap_header(
            self.page_compliance, "备案工作台",
            "影片项目档案 · 备案材料生成 · 完成台本转录 · 红线预检 · 流程跟踪"))

        self.page_set = SettingsPage(self.settings)
        self.stack.addWidget(self._wrap_header(
            self.page_set, "设置", "外部工具路径与流水线参数（AI 引擎为预留）"))

        self._nav_group.button(0).setChecked(True)

    def _wrap_header(self, page: QWidget, title: str, desc: str) -> QWidget:
        """给页面加统一页头（紧凑：标题+描述同行）。"""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(26, 14, 26, 10)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(QLabel(title, objectName="pageTitle"))
        head.addWidget(QLabel(desc, objectName="pageDesc"))
        head.addStretch(1)
        v.addLayout(head)
        v.addWidget(page, 1)
        return wrap

    # ------------------------------------------------------------------ 队列
    def add_task(self, state):
        card = TaskCard(self.settings, state)
        card.ended.connect(self._task_ended)
        self.queue_lay.addWidget(card)
        self._cards.append(card)
        self._start_pending()
        # 切到队列页让用户看到任务启动
        self.stack.setCurrentIndex(1)
        self._nav_group.button(1).setChecked(True)

    def _running_cards(self) -> list[TaskCard]:
        return [c for c in self._cards if c.worker and c.worker.isRunning()]

    def _start_pending(self):
        limit = max(1, self.settings.concurrency)
        for c in self._cards:
            if len(self._running_cards()) >= limit:
                break
            if c.state.stage == "pending" and \
                    not (c.worker and c.worker.isRunning()):
                self.statusBar().showMessage(f"开始任务：{c.state.config.title}")
                c.start()

    def _task_ended(self, task_id: str):
        self.statusBar().showMessage(
            f"任务结束（进行中 {len(self._running_cards())}）", 4000)
        self._start_pending()

    # ------------------------------------------------------------------ 关窗
    def closeEvent(self, event):
        running = self._running_cards()
        if running:
            names = "、".join(c.state.config.title for c in running)
            ret = QMessageBox.question(
                self, "还有任务在运行",
                f"以下任务仍在处理中：{names}\n\n"
                "确定退出吗？（退出将取消这些任务；已完成的归一化可断点恢复）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
            for c in running:
                c.worker.cancel()
            for c in running:
                c.worker.wait(15000)
        event.accept()
