"""「设置」页：工具路径、流水线参数、AI 引擎预留配置。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core.config import PROJECT_ROOT, Settings, save_settings
from ..tools.dcpomatic import DCPoMatic
from ..tools.ffmpeg import FFmpeg


class SettingsPage(QWidget):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        g1 = QGroupBox("外部工具（开源免费）")
        f1 = QFormLayout(g1)
        h1 = QHBoxLayout()
        self.ed_ffmpeg = QLineEdit()
        self.ed_ffmpeg.setPlaceholderText("留空 = 自动检测（tools/ 或 PATH）")
        b1 = QPushButton("自动检测")
        b1.clicked.connect(lambda: self._detect("ffmpeg"))
        b1x = QPushButton("浏览…")
        b1x.clicked.connect(lambda: self._browse("ffmpeg"))
        h1.addWidget(self.ed_ffmpeg, 1)
        h1.addWidget(b1)
        h1.addWidget(b1x)
        f1.addRow("FFmpeg 目录：", h1)
        self.lb_ffmpeg = QLabel()
        f1.addRow("", self.lb_ffmpeg)

        h2 = QHBoxLayout()
        self.ed_dom = QLineEdit()
        self.ed_dom.setPlaceholderText("留空 = 自动检测（默认安装目录或 PATH）")
        b2 = QPushButton("自动检测")
        b2.clicked.connect(lambda: self._detect("dom"))
        b2x = QPushButton("浏览…")
        b2x.clicked.connect(lambda: self._browse("dom"))
        h2.addWidget(self.ed_dom, 1)
        h2.addWidget(b2)
        h2.addWidget(b2x)
        f1.addRow("DCP-o-matic bin：", h2)
        self.lb_dom = QLabel()
        f1.addRow("", self.lb_dom)
        dl = QLabel('未安装？从 <a href="https://dcpomatic.com/download">'
                    'dcpomatic.com/download</a> 免费下载（选 Windows 64-bit）')
        dl.setOpenExternalLinks(True)
        f1.addRow("", dl)
        root.addWidget(g1)

        g2 = QGroupBox("流水线参数")
        f2 = QFormLayout(g2)
        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 4)
        f2.addRow("并行任务数：", self.sp_conc)
        self.cb_standard = QComboBox()
        self.cb_standard.addItem("SMPTE（推荐，新服务器）", "SMPTE")
        self.cb_standard.addItem("Interop（老放映服务器兼容）", "Interop")
        f2.addRow("DCP 标准：", self.cb_standard)
        self.cb_bad = QComboBox()
        self.cb_bad.addItem("跳过坏集继续（推荐）", "skip")
        self.cb_bad.addItem("遇到坏集中止", "abort")
        f2.addRow("坏集策略：", self.cb_bad)
        self.sp_j2k = QSpinBox()
        self.sp_j2k.setRange(60, 250)
        self.sp_j2k.setSuffix(" Mbps")
        f2.addRow("J2K 码率：", self.sp_j2k)
        hint = QLabel("默认 150；超长影片若遇编码器崩溃可降到 100（文件更小）")
        hint.setObjectName("hint")
        f2.addRow("", hint)
        root.addWidget(g2)

        g3 = QGroupBox("AI 引擎（预留，当前版本未启用）")
        g3.setEnabled(False)
        f3 = QFormLayout(g3)
        self.ed_ai_upmix = QLineEdit()
        self.ed_ai_upmix.setPlaceholderText(
            "未来：AI 上混命令模板，如 myai.exe --in {input} --out {output} "
            "--layout {layout}")
        f3.addRow("AI 上混命令：", self.ed_ai_upmix)
        self.ed_enhance = QLineEdit()
        self.ed_enhance.setPlaceholderText(
            "未来：AI 超分命令模板，如 video2x -i {input} -o {output}")
        f3.addRow("AI 超分命令：", self.ed_enhance)
        root.addWidget(g3)

        btn = QPushButton("保存设置")
        btn.clicked.connect(self._save)
        root.addWidget(btn)
        root.addStretch(1)

    # ------------------------------------------------------------------ 功能
    def _browse(self, which: str):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择目录")
        if d:
            (self.ed_ffmpeg if which == "ffmpeg" else self.ed_dom).setText(d)

    def _detect(self, which: str):
        try:
            if which == "ffmpeg":
                ff = FFmpeg.discover(self.ed_ffmpeg.text() or None, PROJECT_ROOT)
                self.lb_ffmpeg.setText(f"✅ {ff.ffmpeg}（版本 {ff.version()}）")
            else:
                dom = DCPoMatic.discover(self.ed_dom.text() or None, PROJECT_ROOT)
                self.lb_dom.setText(f"✅ {dom.cli_exe}")
        except Exception as e:
            (self.lb_ffmpeg if which == "ffmpeg" else self.lb_dom).setText(
                f"❌ {e}")

    def _load(self):
        s = self.settings
        self.ed_ffmpeg.setText(s.ffmpeg_dir)
        self.ed_dom.setText(s.dcpomatic_dir)
        self.sp_conc.setValue(s.concurrency)
        self.cb_standard.setCurrentIndex(
            0 if s.standard == "SMPTE" else 1)
        self.cb_bad.setCurrentIndex(0 if s.bad_episode_policy == "skip" else 1)
        self.sp_j2k.setValue(s.j2k_bitrate_mbps)
        self.ed_ai_upmix.setText(s.engine_cfg.get("ai_upmix_cmd", ""))
        self.ed_enhance.setText(s.engine_cfg.get("enhance_cmd", ""))
        self._detect("ffmpeg")
        self._detect("dom")

    def _save(self):
        s = self.settings
        s.ffmpeg_dir = self.ed_ffmpeg.text().strip()
        s.dcpomatic_dir = self.ed_dom.text().strip()
        s.concurrency = self.sp_conc.value()
        s.standard = self.cb_standard.currentData()
        s.bad_episode_policy = self.cb_bad.currentData()
        s.j2k_bitrate_mbps = self.sp_j2k.value()
        s.engine_cfg["ai_upmix_cmd"] = self.ed_ai_upmix.text().strip()
        s.engine_cfg["enhance_cmd"] = self.ed_enhance.text().strip()
        save_settings(s)
        self.window().statusBar().showMessage("设置已保存 ✓", 3000)
