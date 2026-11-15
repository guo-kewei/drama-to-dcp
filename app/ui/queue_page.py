"""「任务队列」页：任务卡片（进度、阶段、操作按钮、日志查看）。"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton,
                               QTextEdit, QVBoxLayout, QWidget)

from ..core.task import TaskState, stage_label
from .workers import ConvertWorker


class TaskCard(QWidget):
    """单个任务卡片。"""
    ended = Signal(str)            # task_id（任务结束时通知调度器）

    def __init__(self, settings, state: TaskState, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = state
        self.worker: ConvertWorker | None = None
        self._logs: list[str] = []
        self._build_ui()
        self._sync_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setObjectName("taskCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.lb_title = QLabel(objectName="taskTitle")
        top.addWidget(self.lb_title, 1)
        self.lb_stage = QLabel(objectName="stageChip")
        top.addWidget(self.lb_stage)
        lay.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p%")
        lay.addWidget(self.bar)

        mid = QHBoxLayout()
        self.lb_msg = QLabel(objectName="cardMsg")
        self.lb_msg.setWordWrap(True)
        mid.addWidget(self.lb_msg, 1)
        lay.addLayout(mid)

        btns = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_retry = QPushButton("重试")
        self.btn_retry.clicked.connect(self.retry)
        self.btn_open = QPushButton("打开输出目录")
        self.btn_open.clicked.connect(self._open_dir)
        self.btn_log = QPushButton("日志")
        self.btn_log.clicked.connect(self._show_log)
        for b in (self.btn_cancel, self.btn_retry, self.btn_open, self.btn_log):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    # ------------------------------------------------------------------ 运行
    def start(self):
        from .workers import ConvertWorker
        self.worker = ConvertWorker(self.settings, self.state)
        self.worker.stage_changed.connect(self._on_stage)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.message.connect(self._on_msg)
        self.worker.log_line.connect(self._on_log)
        self.worker.finished.connect(self._on_finish)
        self.worker.start()
        self._sync_ui()

    def retry(self):
        """重试：从断点续跑（已归一化的集不会重做）。"""
        if self.worker and self.worker.isRunning():
            return
        if self.state.stage == "done":
            QMessageBox.information(self, "提示", "该任务已成功完成，无需重试。")
            return
        self.state.stage = "pending"
        self.state.error = ""
        self.start()

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lb_msg.setText("正在取消…")

    # ------------------------------------------------------------------ 回调
    def _on_stage(self, key: str, label: str):
        self.state.stage = key
        self._sync_ui()

    def _on_progress(self, p: float):
        self.state.progress = p
        self.bar.setValue(int(p * 1000))

    def _on_msg(self, m: str):
        self.lb_msg.setText(m)

    def _on_log(self, line: str):
        self._logs.append(line)
        if len(self._logs) > 4000:
            self._logs = self._logs[-2000:]

    def _on_finish(self, result: TaskState):
        self.state = result
        self._sync_ui()
        if result.stage == "done":
            self._on_msg(f"✅ 完成 → {result.dcp_output_dir}")
        self.ended.emit(self.state.task_id)

    # ------------------------------------------------------------------ 其他
    def _sync_ui(self):
        st = self.state
        self.lb_title.setText(
            f"🎬 {st.config.title}（{st.config.resolution.upper()} · "
            f"{st.resolved_container or '…'} · {st.config.audio_layout}）")
        stage = stage_label(st.stage)
        tone = {"done": "ok", "failed": "bad", "cancelled": "bad",
                "pending": "idle"}.get(st.stage, "")
        self.lb_stage.setProperty("tone", tone)
        self.lb_stage.setText(stage)
        self.lb_stage.style().unpolish(self.lb_stage)
        self.lb_stage.style().polish(self.lb_stage)
        # 完成态进度条必满（防御：状态恢复/异常路径下 progress 可能未置 1）
        frac = 1.0 if st.stage == "done" else st.progress
        self.bar.setValue(int(frac * 1000))
        running = bool(self.worker and self.worker.isRunning())
        self.btn_cancel.setEnabled(running)
        self.btn_retry.setEnabled(not running and st.stage != "done")
        if st.error and not running:
            self.lb_msg.setText(f"❌ {st.error[:300]}")

    def _open_dir(self):
        st = self.state
        path = st.dcp_output_dir
        if not path:
            path = str(self.settings.dcp_dir(Path(st.config.source_dir)))
        target = path if Path(path).is_dir() else str(Path(path).parent)
        try:
            os.startfile(target)      # type: ignore[attr-defined]
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def _show_log(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"日志 — {self.state.config.title}")
        dlg.resize(780, 480)
        v = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText("\n".join(self._logs) or "（暂无日志）")
        v.addWidget(te)
        btn = QPushButton("复制全部")
        btn.clicked.connect(
            lambda: QApplication.clipboard().setText(te.toPlainText()))
        v.addWidget(btn)
        dlg.exec()
