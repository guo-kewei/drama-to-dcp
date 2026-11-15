"""「备案工作台」页：项目档案 / 材料生成 / 红线预检 / 流程跟踪。"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from ..compliance import documents, redline, transcript
from ..compliance.models import FilmProject, PROCESS_STAGES
from ..core.config import PROJECT_ROOT
from .theme import ACCENT2

ROOT = PROJECT_ROOT          # 备案项目根：<项目根>/备案/<项目ID>


class TranscriptWorker(QThread):
    progress = Signal(str)
    done = Signal(list)              # [(start, end, text)]
    failed = Signal(str)

    def __init__(self, media: Path, parent=None):
        super().__init__(parent)
        self.media = media

    def run(self):
        try:
            segs = transcript.transcribe(
                self.media, engine="auto",
                on_progress=lambda m: self.progress.emit(m))
            self.done.emit(segs)
        except Exception as e:
            self.failed.emit(str(e))


class CompliancePage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.project: FilmProject | None = None
        self._transcript: list[tuple[float, float, str]] = []
        self._worker: TranscriptWorker | None = None
        self._build_ui()
        self._reload_projects()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setSpacing(14)

        # 左：项目列表
        left = QVBoxLayout()
        left.addWidget(QLabel("备案项目", objectName="stepTitle"))
        self.lst = QListWidget()
        self.lst.setMinimumWidth(210)
        self.lst.currentRowChanged.connect(self._on_select)
        left.addWidget(self.lst, 1)
        row = QHBoxLayout()
        b_new = QPushButton("新建")
        b_new.clicked.connect(self._new_project)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del_project)
        row.addWidget(b_new)
        row.addWidget(b_del)
        left.addLayout(row)
        lay.addLayout(left)

        # 右：标签页
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_info(), "项目信息")
        self.tabs.addTab(self._tab_docs(), "材料生成")
        self.tabs.addTab(self._tab_redline(), "红线预检")
        self.tabs.addTab(self._tab_tracker(), "流程跟踪")
        lay.addWidget(self.tabs, 1)

    # ---------------------------------------------------------------- 项目信息
    def _tab_info(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("影片档案（对应备案申请表字段）")
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.ed = {}
        fields = [
            ("title_cn", "中文片名："), ("title_en", "英文译名："),
            ("genre", "影片类型："), ("source", "素材来源："),
            ("duration_min", "片长（分钟）："), ("aspect", "画幅规格："),
            ("production_company", "出品单位（法人）："),
            ("copyright_owner", "著作权归属："),
            ("director", "导演："), ("screenwriter", "编剧："),
            ("producer", "制片人："), ("cast", "主要演员："),
        ]
        for key, label in fields:
            e = QLineEdit()
            self.ed[key] = e
            f.addRow(label, e)
        v.addWidget(g)

        g2 = QGroupBox("剧情梗概（备案要求约 1000 字）")
        v2 = QVBoxLayout(g2)
        self.tx_syn = QTextEdit()
        self.tx_syn.textChanged.connect(self._syn_changed)
        v2.addWidget(self.tx_syn)
        self.lb_syn = QLabel("0 字")
        self.lb_syn.setObjectName("hint")
        v2.addWidget(self.lb_syn)
        v.addWidget(g2)

        b = QPushButton("保存项目")
        b.clicked.connect(self._save_project)
        v.addWidget(b)
        return w

    def _syn_changed(self):
        if self.project is not None:
            self.project.synopsis = self.tx_syn.toPlainText()
        n = len("".join(self.tx_syn.toPlainText().split()))
        color = "#34d399" if 300 <= n <= 1500 else "#fbbf24"
        self.lb_syn.setText(f"{n} 字" + ("" if 300 <= n <= 1500 else
                                          "（建议 300-1500 字）"))

    # ---------------------------------------------------------------- 材料生成
    def _tab_docs(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        g1 = QGroupBox("关联文件")
        f1 = QFormLayout(g1)
        h1 = QHBoxLayout()
        self.ed_dcp = QLineEdit()
        self.ed_dcp.setPlaceholderText("DCP 成品目录（用于技术自检报告）")
        b1 = QPushButton("选择…")
        b1.clicked.connect(lambda: self._pick_dir(self.ed_dcp))
        h1.addWidget(self.ed_dcp, 1)
        h1.addWidget(b1)
        f1.addRow("DCP 目录：", h1)
        h2 = QHBoxLayout()
        self.ed_media = QLineEdit()
        self.ed_media.setPlaceholderText("成片视频（用于完成台本转录）")
        b2 = QPushButton("选择…")
        b2.clicked.connect(lambda: self._pick_file(self.ed_media))
        h2.addWidget(self.ed_media, 1)
        h2.addWidget(b2)
        f1.addRow("成片母版：", h2)
        v.addWidget(g1)

        g2 = QGroupBox("生成材料（docx 输出到 备案/<项目>/materials/）")
        grid = QHBoxLayout(g2)
        for label, fn in (
                ("① 备案报告", self._gen_filing),
                ("② 主创登记表", self._gen_crew),
                ("③ 完成台本（转录）", self._gen_transcript),
                ("④ DCP 技术自检报告", self._gen_qc)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            grid.addWidget(b)
        v.addWidget(g2)

        self.lb_trans = QLabel("尚未转录")
        self.lb_trans.setObjectName("hint")
        v.addWidget(self.lb_trans)
        self.txt_out = QPlainTextEdit()
        self.txt_out.setReadOnly(True)
        self.txt_out.setPlaceholderText("生成的材料与转录进度将显示在这里")
        v.addWidget(self.txt_out, 1)
        return w

    # ---------------------------------------------------------------- 红线预检
    def _tab_redline(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("对照《电影产业促进法》第16条与《微短剧发展管理办法》"
                      "红线方向的敏感词启发式扫描。仅辅助降低退回率，"
                      "不替代官方审查。词表：config/redline_keywords.json")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.tx_scan = QPlainTextEdit()
        self.tx_scan.setPlaceholderText("粘贴台本/字幕文本，或完成转录后点击下方按钮")
        v.addWidget(self.tx_scan, 1)
        row = QHBoxLayout()
        b1 = QPushButton("用完成台本文本")
        b1.clicked.connect(self._use_transcript_text)
        b2 = QPushButton("开始扫描")
        b2.clicked.connect(self._do_scan)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        self.tbl_scan = QTableWidget(0, 4)
        self.tbl_scan.setHorizontalHeaderLabels(
            ["红线类别", "命中词", "次数", "上下文示例"])
        self.tbl_scan.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl_scan.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_scan.setAlternatingRowColors(True)
        self.tbl_scan.setShowGrid(False)
        v.addWidget(self.tbl_scan, 1)
        return w

    # ---------------------------------------------------------------- 流程跟踪
    def _tab_tracker(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("记录各环节日期（参考周期：备案公示 2-6 周 · 省初审≤30日 · "
                      "国家终审≤30日 · 技审+领证 2-3 周；单部全程约 3-5 个月）")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        g = QGroupBox("登记进度")
        f = QFormLayout(g)
        self.cb_stage = QComboBox()
        for key, label in PROCESS_STAGES:
            self.cb_stage.addItem(label, key)
        self.ed_date = QLineEdit()
        self.ed_date.setPlaceholderText("YYYY-MM-DD（留空=今天）")
        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("备注（如：已公示/退回修改原因）")
        f.addRow("环节：", self.cb_stage)
        f.addRow("日期：", self.ed_date)
        f.addRow("备注：", self.ed_note)
        b = QPushButton("保存记录")
        b.clicked.connect(self._add_stage)
        f.addRow("", b)
        v.addWidget(g)

        self.tbl_stage = QTableWidget(0, 3)
        self.tbl_stage.setHorizontalHeaderLabels(["日期", "环节", "备注"])
        self.tbl_stage.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_stage.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_stage.setAlternatingRowColors(True)
        self.tbl_stage.setShowGrid(False)
        v.addWidget(self.tbl_stage, 1)
        return w

    # ---------------------------------------------------------------- 项目操作
    def _reload_projects(self):
        self.lst.blockSignals(True)
        self.lst.clear()
        for p in FilmProject.list_all(ROOT):
            self.lst.addItem(p.title_cn or p.id)
            self.lst.item(self.lst.count() - 1).setData(Qt.UserRole, p.id)
        self.lst.blockSignals(False)
        if self.lst.count():
            self.lst.setCurrentRow(0)

    def _on_select(self, row: int):
        if row < 0 or row >= self.lst.count():
            return
        pid = self.lst.item(row).data(Qt.UserRole)
        for p in FilmProject.list_all(ROOT):
            if p.id == pid:
                self._load_project(p)
                return

    def _load_project(self, p: FilmProject):
        self.project = p
        for key, e in self.ed.items():
            val = getattr(p, key)
            e.setText(str(val) if val not in (None, 0) else "")
        self.tx_syn.setPlainText(p.synopsis)
        self.ed_dcp.setText(p.dcp_dir)
        self.ed_media.setText(p.master_media)
        self._refresh_stage_table()

    def _new_project(self):
        p = FilmProject(genre="故事片")
        p.save(ROOT)
        self._reload_projects()
        for i in range(self.lst.count()):
            if self.lst.item(i).data(Qt.UserRole) == p.id:
                self.lst.setCurrentRow(i)

    def _del_project(self):
        row = self.lst.currentRow()
        if row < 0 or self.project is None:
            return
        if QMessageBox.question(
                self, "删除项目",
                f"确定删除「{self.project.title_cn or self.project.id}」？"
                "（材料文件将一并删除）") != QMessageBox.Yes:
            return
        import shutil
        shutil.rmtree(self.project.dir(ROOT), ignore_errors=True)
        self.project = None
        self._reload_projects()

    def _save_project(self):
        if self.project is None:
            QMessageBox.information(self, "提示", "请先新建或选择项目")
            return
        p = self.project
        for key, e in self.ed.items():
            raw = e.text().strip()
            if key == "duration_min":
                p.duration_min = int(raw) if raw.isdigit() else 0
            else:
                setattr(p, key, raw)
        p.synopsis = self.tx_syn.toPlainText()
        p.dcp_dir = self.ed_dcp.text().strip()
        p.master_media = self.ed_media.text().strip()
        p.save(ROOT)
        row = self.lst.currentRow()
        self._reload_projects()
        if row >= 0:
            self.lst.setCurrentRow(min(row, self.lst.count() - 1))
        self._log_out(f"✅ 项目已保存：{p.dir(ROOT)}")

    # ---------------------------------------------------------------- 材料生成
    def _pick_dir(self, ed: QLineEdit):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择目录")
        if d:
            ed.setText(d)

    def _pick_file(self, ed: QLineEdit):
        from PySide6.QtWidgets import QFileDialog
        d, _ = QFileDialog.getOpenFileName(self, "选择文件", "",
                                           "视频/音频 (*.mp4 *.mov *.mkv *.wav)")
        if d:
            ed.setText(d)

    def _log_out(self, msg: str):
        self.txt_out.appendPlainText(msg)

    def _gen_filing(self):
        if not self._require_project():
            return
        out = documents.build_filing_report(ROOT, self.project)
        self._log_out(f"✅ 已生成 {out}")

    def _gen_crew(self):
        if not self._require_project():
            return
        out = documents.build_crew_form(ROOT, self.project)
        self._log_out(f"✅ 已生成 {out}")

    def _gen_qc(self):
        if not self._require_project():
            return
        dcp = self.ed_dcp.text().strip()
        if not dcp or not Path(dcp).is_dir():
            QMessageBox.warning(self, "提示", "请先选择 DCP 成品目录")
            return
        out, info = documents.build_qc_report(ROOT, self.project, Path(dcp))
        self._log_out(f"✅ 已生成 {out}\n   参数：{info}")

    def _gen_transcript(self):
        if not self._require_project():
            return
        media = self.ed_media.text().strip()
        if not media or not Path(media).is_file():
            QMessageBox.warning(self, "提示", "请先选择成片母版文件")
            return
        if self._worker and self._worker.isRunning():
            return
        self.lb_trans.setText("转录中…")
        self._worker = TranscriptWorker(Path(media))
        self._worker.progress.connect(self._log_out)
        self._worker.progress.connect(self.lb_trans.setText)
        self._worker.done.connect(self._on_transcript_done)
        self._worker.failed.connect(self._on_transcript_fail)
        self._worker.start()

    def _on_transcript_done(self, segs: list):
        self._transcript = segs
        if self.project is not None:
            out = documents.build_transcript_doc(ROOT, self.project, segs)
            self._log_out(f"✅ 转录完成 {len(segs)} 段 → {out}")
            self.lb_trans.setText(f"转录完成：{len(segs)} 段")
        text = "\n".join(t for _, _, t in segs)
        self.tx_scan.setPlainText(text)

    def _on_transcript_fail(self, err: str):
        self.lb_trans.setText("转录失败")
        self._log_out(f"❌ 转录失败: {err[:300]}")

    def _require_project(self) -> bool:
        if self.project is None:
            QMessageBox.information(self, "提示", "请先新建或选择项目")
            return False
        return True

    # ---------------------------------------------------------------- 红线/流程
    def _use_transcript_text(self):
        if self._transcript:
            self.tx_scan.setPlainText(
                "\n".join(t for _, _, t in self._transcript))

    def _do_scan(self):
        hits = redline.scan(self.tx_scan.toPlainText())
        self.tbl_scan.setRowCount(len(hits))
        for r, h in enumerate(hits):
            for c, v in enumerate((h["category"], "、".join(h["keywords"]),
                                   str(h["count"]), " … ".join(h["samples"][:2]))):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setForeground(Qt.red)
                self.tbl_scan.setItem(r, c, item)
        if not hits:
            QMessageBox.information(self, "扫描完成", "未命中预置红线关键词。"
                                    "（词表有限，不能替代官方审查）")

    def _add_stage(self):
        if not self._require_project():
            return
        from ..compliance.models import StageRecord
        import re
        import time as _t
        date = self.ed_date.text().strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
            date = _t.strftime("%Y-%m-%d")
        rec = StageRecord(key=self.cb_stage.currentData(), date=date,
                          note=self.ed_note.text().strip())
        self.project.stage_log.append(rec)
        self.project.save(ROOT)
        self._refresh_stage_table()
        self.ed_note.clear()

    def _refresh_stage_table(self):
        if self.project is None:
            return
        labels = dict(PROCESS_STAGES)
        log = sorted(self.project.stage_log, key=lambda s: s.date)
        self.tbl_stage.setRowCount(len(log))
        for r, s in enumerate(log):
            self.tbl_stage.setItem(r, 0, QTableWidgetItem(s.date))
            self.tbl_stage.setItem(r, 1, QTableWidgetItem(
                labels.get(s.key, s.key)))
            self.tbl_stage.setItem(r, 2, QTableWidgetItem(s.note))
