"""「新建转换」页：选文件夹 → 自动扫描 → 输出参数 → 开始转换（傻瓜化）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.naming import isdcf_preview, sanitize_dcp_name, suggest_dcp_name
from ..core.task import CONTAINERS, Episode, TaskConfig, TaskState
from .workers import ScanWorker


class ElidedLabel(QLabel):
    """超宽文本中段省略（QLabel 默认撑最小宽度不省略）。"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text

    def setText(self, text: str):
        self._full = text
        self._refit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refit()

    def _refit(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(
            self._full, Qt.ElideMiddle, max(self.width() - 22, 60)))


class NewTaskPage(QWidget):
    task_created = Signal(object)          # TaskState

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._episodes: list[Episode] = []
        self._summary: dict = {}
        self._scan_worker: ScanWorker | None = None
        self._retired_workers: list[ScanWorker] = []   # 防旧线程被 GC 崩溃
        self._scan_gen = 0                 # 扫描代数：仅接受最新一代的结果
        self._build_ui()
        self._apply_defaults()

    # ------------------------------------------------------------------ UI
    def _step_card(self, num: str, title: str,
                   subtitle: str = "") -> tuple[QGroupBox, QVBoxLayout]:
        """步骤卡片：醒目的数字圆徽 + 大标题（+ 可选灰色副标题）。"""
        g = QGroupBox()
        v = QVBoxLayout(g)
        v.setContentsMargins(18, 12, 18, 12)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel(num)
        badge.setObjectName("stepBadge")
        badge.setAlignment(Qt.AlignCenter)
        head.addWidget(badge)
        tcol = QVBoxLayout()
        tcol.setSpacing(1)
        tcol.addWidget(QLabel(title, objectName="stepTitle"))
        if subtitle:
            tcol.addWidget(QLabel(subtitle, objectName="stepSub"))
        head.addLayout(tcol)
        head.addStretch(1)
        v.addLayout(head)
        # 标题分隔线
        line = QFrame()
        line.setObjectName("stepLine")
        line.setFrameShape(QFrame.HLine)
        v.addWidget(line)
        return g, v

    def _build_ui(self):
        # 外层滚动容器：小屏幕/缩放时内容不被裁切
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(2, 2, 8, 2)
        root.setSpacing(10)

        # ① 源文件夹
        g1, v1 = self._step_card("1", "选择短剧文件夹",
                                 "整个文件夹的多集将按文件名顺序合并为一部电影")
        h1 = QHBoxLayout()
        self.ed_folder = QLineEdit()
        self.ed_folder.setPlaceholderText("点击「浏览」选择，或直接把文件夹拖到这里")
        self.ed_folder.setReadOnly(True)
        self.ed_folder.setAcceptDrops(True)
        self.ed_folder.dragEnterEvent = self._drag_enter
        self.ed_folder.dropEvent = self._drop
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._pick_folder)
        h1.addWidget(self.ed_folder, 1)
        h1.addWidget(btn)
        v1.addLayout(h1)
        self.lb_scan = QLabel("尚未选择文件夹")
        self.lb_scan.setObjectName("hint")
        self.lb_scan.setWordWrap(True)
        v1.addWidget(self.lb_scan)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["#", "文件", "分辨率", "帧率", "时长", "音频"])
        # 列宽：文件列自适应拉伸，其余按内容固定，避免末列孤悬
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, width in ((0, 44), (2, 110), (3, 70), (4, 80), (5, 230)):
            self.table.setColumnWidth(col, width)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)      # 单行省略策略，避免折行溢出
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(88)    # 集数多时表内滚动，不撑爆页面
        self.table.setMaximumHeight(158)
        v1.addWidget(self.table)

        # ② 输出设置：画面/音频双栏 + DCP 信息
        g2, v2 = self._step_card("2", "输出设置")
        cols = QHBoxLayout()
        cols.setSpacing(12)

        gv = QGroupBox("画面")
        fv = QFormLayout(gv)
        fv.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fv.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.cb_container = QComboBox()
        self.cb_container.addItem("自动匹配（推荐）", "auto")
        self.cb_container.addItem("Flat 1.85:1（1998×1080）", "flat")
        self.cb_container.addItem("Scope 2.39:1（2048×858）", "scope")
        self.cb_container.addItem("Full 1.90:1（2048×1080）⚠需放映端预设",
                                  "full")
        fv.addRow("目标画幅：", self.cb_container)
        self.cb_res = QComboBox()
        self.cb_res.addItem("2K（推荐，速度快）", "2k")
        self.cb_res.addItem("4K（更清晰，速度慢）", "4k")
        fv.addRow("分辨率：", self.cb_res)
        self.cb_fit = QComboBox()
        self.cb_fit.addItem("轻微裁切填满（推荐）", "fill")
        self.cb_fit.addItem("完整保留画面（加黑边）", "fit")
        fv.addRow("画面策略：", self.cb_fit)
        cols.addWidget(gv, 1)

        ga = QGroupBox("音频")
        fa = QFormLayout(ga)
        fa.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fa.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.cb_audio = QComboBox()
        self.cb_audio.addItem("5.1 环绕声（推荐）", "5.1")
        self.cb_audio.addItem("7.1 环绕声（需确认放映端支持）", "7.1")
        self.cb_audio.addItem("立体声", "stereo")
        fa.addRow("声道：", self.cb_audio)
        self.cb_engine = QComboBox()
        self.cb_engine.addItem("规则上混（默认，对白中置）", "rule")
        self.cb_engine.addItem("AI 上混（预留，未来启用）", "ai")
        self.cb_engine.model().item(1).setEnabled(False)   # v1 置灰
        fa.addRow("上混引擎：", self.cb_engine)
        self.sp_gap = QDoubleSpinBox()
        self.sp_gap.setRange(0.0, 5.0)
        self.sp_gap.setSingleStep(0.1)
        self.sp_gap.setSuffix(" 秒")
        self.sp_gap.setValue(self.settings.default_gap)
        fa.addRow("集间黑场：", self.sp_gap)
        cols.addWidget(ga, 1)
        # 双栏标签列等宽，控件起始位置对齐
        for form in (fv, fa):
            for row in range(form.count()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                if item and item.widget():
                    item.widget().setMinimumWidth(84)
        v2.addLayout(cols)

        f2 = QFormLayout()
        f2.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f2.setHorizontalSpacing(14)

        # 影片名称 / DCP 名称 并排一行，压缩纵向高度
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(QLabel("影片名称："))
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("显示名称（可中文）")
        self.ed_title.textChanged.connect(self._title_changed)
        name_row.addWidget(self.ed_title, 5)
        name_row.addWidget(QLabel("DCP 名称："))
        self.ed_dcp_name = QLineEdit()
        self.ed_dcp_name.setPlaceholderText(
            "大写字母/数字/下划线；中文自动转拼音")
        self.ed_dcp_name.textChanged.connect(self._update_preview)
        name_row.addWidget(self.ed_dcp_name, 4)
        f2.addRow("", name_row)

        # ISDCF 规范最终名称实时预览（超长中段省略，tooltip 显全名）
        self.lb_preview = ElidedLabel("—")
        self.lb_preview.setObjectName("previewName")
        f2.addRow("", self.lb_preview)

        self.cb_ctype = QComboBox()
        self.cb_ctype.addItem("长片（FTR）", "FTR")
        self.cb_ctype.addItem("预告片（TLR）", "TLR")
        f2.addRow("内容类型：", self.cb_ctype)
        for cb in (self.cb_container, self.cb_res, self.cb_audio, self.cb_ctype):
            cb.currentIndexChanged.connect(self._update_preview)
        v2.addLayout(f2)

        # ③ 输出位置 + 开始
        g3, v3 = self._step_card("3", "输出位置")
        h3 = QHBoxLayout()
        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText("默认：源文件夹同级「DCP输出」目录")
        btn3 = QPushButton("浏览…")
        btn3.clicked.connect(self._pick_out)
        h3.addWidget(self.ed_out, 1)
        h3.addWidget(btn3)
        v3.addLayout(h3)

        self.btn_go = QPushButton("开始转换 →")
        self.btn_go.setObjectName("ctaBtn")
        self.btn_go.setMinimumHeight(52)
        self.btn_go.setMinimumWidth(320)
        self.btn_go.setCursor(Qt.PointingHandCursor)
        self.btn_go.setEnabled(False)
        self.btn_go.clicked.connect(self._start)

        # 布局：三步纵向排列（步骤3在底部通栏），主按钮居中收尾
        # 下拉框按最长选项文本撑宽会挤爆双栏最小宽度：
        # 显式设置最小宽度覆盖其 minimumSizeHint（框内省略、下拉列表完整）
        for cb in (self.cb_container, self.cb_res, self.cb_fit,
                   self.cb_audio, self.cb_engine, self.cb_ctype):
            cb.setMinimumContentsLength(12)
            cb.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumWidth(150)
        root.addWidget(g1)
        root.addWidget(g2)
        root.addWidget(g3)
        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        cta_row.addWidget(self.btn_go)
        cta_row.addStretch(1)
        root.addLayout(cta_row)
        root.addStretch(1)

    # ------------------------------------------------------------------ 默认值
    def _apply_defaults(self):
        """从持久化设置读取新任务默认参数（设置页/配置文件可改）。"""
        s = self.settings
        for cb, key, choices in (
                (self.cb_container, s.default_container,
                 ("auto", "flat", "scope", "full")),
                (self.cb_res, s.default_resolution, ("2k", "4k")),
                (self.cb_audio, s.default_audio_layout,
                 ("5.1", "7.1", "stereo"))):
            i = cb.findData(key) if key in choices else 0
            cb.setCurrentIndex(max(0, i))
        # 上混引擎默认（AI 在 v1 置灰，非 rule 一律回落规则引擎）
        if s.default_upmix_engine == "rule":
            self.cb_engine.setCurrentIndex(0)

    # ------------------------------------------------------------------ 事件
    def _drag_enter(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def _drop(self, e):
        urls = e.mimeData().urls()
        if urls:
            p = Path(urls[0].toLocalFile())
            if p.is_dir():
                self.set_folder(str(p))

    def _pick_folder(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择短剧文件夹")
        if d:
            self.set_folder(d)

    def _pick_out(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择输出根目录")
        if d:
            self.ed_out.setText(d)

    def _title_changed(self, text):
        # 用户没手改 DCP 名称时自动跟随影片名（中文自动转拼音）
        if not self.ed_dcp_name.isModified():
            self.ed_dcp_name.setText(suggest_dcp_name(text))

    def _update_preview(self, *_):
        """按 ISDCF DCNC 规范实时预览最终 DCP 名称。"""
        container = self.cb_container.currentData()
        if container == "auto":
            container = (self._summary.get("recommended_container", "flat")
                         if self._summary else "flat")
        self.lb_preview.setText(
            "ISDCF：" + isdcf_preview(
                self.ed_dcp_name.text() or "UNTITLED",
                self.cb_ctype.currentData(), container,
                self.cb_res.currentData(), self.cb_audio.currentData(),
                self.settings.standard)
            + "（后缀打包时自动生成）")
        self.lb_preview.setToolTip("最终 DCP 名称遵循 ISDCF 数字影院命名规范；"
                                   "日期等后缀由 DCP-o-matic 打包时自动生成")

    # ------------------------------------------------------------------ 扫描
    def set_folder(self, folder: str):
        self.ed_folder.setText(folder)
        if not self.ed_title.text():
            self.ed_title.setText(Path(folder).name)
            self.ed_dcp_name.setText(suggest_dcp_name(Path(folder).name))
        self._update_preview()
        self.lb_scan.setText("正在扫描探测…")
        self.table.setRowCount(0)
        self.btn_go.setEnabled(False)
        # 扫描代数 +1：旧扫描（若仍在跑）的结果将被忽略，允许立即换文件夹重扫
        self._scan_gen += 1
        gen = self._scan_gen
        # 旧 worker 若仍在运行，保留引用直至其自然结束（防 GC 销毁运行中
        # QThread 导致进程崩溃），结束后自我清理
        if self._scan_worker is not None:
            old = self._scan_worker
            self._retired_workers.append(old)
            old.finished.connect(old.deleteLater)
            old.finished.connect(
                lambda w=old: self._retired_workers.remove(w)
                if w in self._retired_workers else None)
        worker = ScanWorker(folder, self.settings)
        worker.progress.connect(
            lambda i, n, name: self._on_scan_progress(gen, i, n, name))
        worker.done.connect(
            lambda eps, summary, _g=gen: self._scan_done(_g, eps, summary))
        worker.failed.connect(
            lambda err, _g=gen: self._scan_failed(_g, err))
        self._scan_worker = worker
        worker.start()

    def _on_scan_progress(self, gen, i, n, name):
        if gen == self._scan_gen:
            self.lb_scan.setText(f"扫描中 {i}/{n}：{name}")

    def _scan_done(self, gen: int, eps_raw: list, summary: dict):
        if gen != self._scan_gen:      # 旧一代扫描的结果，丢弃
            return
        self._episodes = [Episode(**d) for d in eps_raw]
        self._summary = summary
        self.table.setRowCount(len(self._episodes))
        for r, e in enumerate(self._episodes):
            bad = bool(e.error)
            vals = [str(e.index), Path(e.path).name,
                    f"{e.width}×{e.height}" if e.width else "—",
                    f"{e.fps:g}" if e.fps else "—",
                    f"{e.duration:.1f}s" if e.duration else "—",
                    f"{e.audio_channels}ch" if e.audio_channels else "无",
                    ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if bad and c == 5:
                    one = (e.error or "").replace("\r", " ").replace("\n", " ")
                    item.setText("❌ " + (one[:24] + "…" if len(one) > 24 else one))
                    item.setToolTip(e.error)
                if bad:
                    item.setForeground(Qt.red)
                self.table.setItem(r, c, item)
        mins = summary["total_duration"] / 60
        rec = CONTAINERS[summary["recommended_container"]]["label"]
        warn = ""
        if summary.get("mixed_resolution"):
            warn = "  ⚠ 各集分辨率不一致，将统一处理"
        self.lb_scan.setText(
            f"✅ 共 {summary['total']} 集（{summary['ok']} 正常 / "
            f"{summary['bad']} 异常，悬停红色项看原因），总时长 {mins:.1f} 分钟，"
            f"源 {summary['width']}×{summary['height']} → 推荐画幅 {rec}"
            f"{warn}")
        self.btn_go.setEnabled(summary["ok"] > 0)
        self._update_preview()

    def _scan_failed(self, gen: int, err: str):
        if gen != self._scan_gen:
            return
        self.lb_scan.setText(f"❌ 扫描失败：{err}")
        self.btn_go.setEnabled(False)

    # ------------------------------------------------------------------ 启动
    def _start(self):
        folder = self.ed_folder.text()
        if not folder or not self._episodes:
            return
        out_override = self.ed_out.text().strip()
        cfg = TaskConfig(
            source_dir=str(Path(folder).resolve()),
            container=self.cb_container.currentData(),
            resolution=self.cb_res.currentData(),
            fit_mode=self.cb_fit.currentData(),
            audio_layout=self.cb_audio.currentData(),
            upmix_engine=self.cb_engine.currentData(),
            dcp_name=sanitize_dcp_name(self.ed_dcp_name.text() or "UNTITLED"),
            title=self.ed_title.text().strip() or Path(folder).name,
            content_type=self.cb_ctype.currentData(),
            gap=float(self.sp_gap.value()),
            bad_episode_policy=self.settings.bad_episode_policy,
            # 任务级输出根（不污染全局设置）
            output_root=str(Path(out_override).resolve()) if out_override else "")
        state = TaskState.new(cfg)
        # 复用已有扫描结果（跳过重新探测）
        state.episodes = self._episodes
        good = [e for e in self._episodes if not e.error]
        from ..core.task import recommend_container
        cont = cfg.container
        if cont == "auto":
            cont = (self._summary.get("recommended_container")
                    or recommend_container(max(e.width for e in good),
                                           max(e.height for e in good)))
        state.resolved_container = cont
        state.expected_total = (sum(e.duration for e in good)
                                + max(len(good) - 1, 0) * cfg.gap)
        self.task_created.emit(state)
