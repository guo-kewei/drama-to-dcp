"""后台工作线程：扫描探测 / 流水线执行（信号驱动 UI 更新）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.config import PROJECT_ROOT, Settings
from ..core.task import TaskState
from ..pipeline.runner import PipelineRunner, RunnerCallbacks
from ..tools.ffmpeg import FFmpeg


class ScanWorker(QThread):
    """文件夹扫描（ffprobe 逐集）。"""
    progress = Signal(int, int, str)     # i, n, name
    done = Signal(list, dict)            # episodes, summary
    failed = Signal(str)

    def __init__(self, folder: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.settings = settings

    def run(self):
        try:
            from ..pipeline.probe import scan_folder
            ff = FFmpeg.discover(self.settings.ffmpeg_dir or None, PROJECT_ROOT)
            eps, summary = scan_folder(
                ff, Path(self.folder),
                on_episode=lambda i, n, name: self.progress.emit(i, n, name))
            self.done.emit(
                [e.__dict__ for e in eps], summary)
        except Exception as e:
            self.failed.emit(str(e))


class ConvertWorker(QThread):
    """完整流水线执行。"""
    stage_changed = Signal(str, str)    # key, label
    progress_changed = Signal(float)    # 0~1
    message = Signal(str)
    log_line = Signal(str)
    finished = Signal(object)           # TaskState

    def __init__(self, settings: Settings, state: TaskState, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = state
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        cbs = RunnerCallbacks(
            on_stage=lambda k, l: self.stage_changed.emit(k, l),
            on_progress=lambda p: self.progress_changed.emit(p),
            on_message=lambda m: self.message.emit(m),
            on_log=lambda l: self.log_line.emit(l))
        try:
            runner = PipelineRunner(
                self.settings, self.state, cbs,
                cancel_flag=lambda: self._cancelled)
            result = runner.run()
        except Exception as e:      # 锁冲突/工具缺失等启动期错误
            # 确保任务卡片总能收到失败态（否则会永远停在"待处理"）
            self.state.stage = "failed"
            self.state.error = str(e)
            self.message.emit(f"❌ 无法启动任务: {e}")
            result = self.state
        self.finished.emit(result)
