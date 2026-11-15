"""全局视觉主题：深色科技风 QSS（集中管理，页面只设 objectName/属性）。"""
from __future__ import annotations

BG = "#0a0f1e"        # 窗口底
SURFACE = "#0f1628"   # 侧栏/面板
CARD = "#121b31"      # 卡片
CARD_HOVER = "#16213c"
LINE = "#1f2a47"      # 描边
TEXT = "#e8eef9"
MUTED = "#9aabc9"
ACCENT = "#3b82f6"
ACCENT2 = "#22d3ee"
OK = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"
FIELD = "#0c1424"     # 输入控件底


def build_qss() -> str:
    return f"""
* {{ font-family: "Microsoft YaHei UI","Microsoft YaHei",sans-serif; outline: none; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget {{ background: transparent; color: {TEXT}; font-size: 13px; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px; }}

/* ---------- 侧栏 ---------- */
QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
QLabel#logoName {{ color: {TEXT}; font-size: 16px; font-weight: 700; background: transparent; }}
QLabel#logoSub {{ color: {ACCENT2}; font-size: 11px; background: transparent; letter-spacing: 1px; }}
QPushButton#navBtn {{
    text-align: left; padding: 11px 14px; border: none; border-radius: 9px;
    color: {MUTED}; font-size: 14px; background: transparent; margin: 3px 10px;
}}
QPushButton#navBtn:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QPushButton#navBtn:checked {{
    background: {CARD_HOVER}; color: {TEXT}; font-weight: 700;
    border-left: 3px solid {ACCENT};
}}
QLabel#sideFooter {{ color: #4d5f80; font-size: 11px; padding: 12px; background: transparent; }}

/* ---------- 卡片 ---------- */
QGroupBox, QFrame#card {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 12px;
    padding: 14px; margin-top: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; top: 2px; padding: 0 6px;
    color: {ACCENT2}; font-size: 13px; font-weight: 700;
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {FIELD}; border: 1px solid {LINE}; border-radius: 8px;
    padding: 7px 10px; color: {TEXT}; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: #54658a; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {LINE}; color: {TEXT};
    selection-background-color: {CARD_HOVER}; selection-color: {ACCENT2};
    outline: none; padding: 4px;
}}
QComboBox::disabled, QLineEdit::disabled {{ color: #54658a; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {CARD}; border: none; width: 18px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {CARD_HOVER}; color: {TEXT}; border: 1px solid {LINE};
    border-radius: 8px; padding: 7px 16px; font-size: 13px;
}}
QPushButton:hover {{ background: #1c2a4a; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #16213c; }}
QPushButton:disabled {{ color: #4d5f80; border-color: {LINE}; background: {SURFACE}; }}
QPushButton#ctaBtn {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 {ACCENT2});
    color: white; border: none; border-radius: 10px; padding: 12px;
    font-size: 17px; font-weight: 800; letter-spacing: 3px;
}}
QPushButton#ctaBtn:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #67e8f9); }}
QPushButton#ctaBtn:pressed {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1d4ed8, stop:1 #0891b2); }}
QPushButton#ctaBtn:disabled {{ background: #2a3550; color: #64748b; }}
QPushButton#ghostBtn {{ background: transparent; }}

/* ---------- 表格 ---------- */
QTableWidget {{
    background: {FIELD}; alternate-background-color: #0f1729;
    border: 1px solid {LINE}; border-radius: 10px;
}}
QTableWidget::item {{ padding: 5px 8px; border: none; }}
QTableWidget::item:selected {{ background: rgba(59,130,246,0.28); color: {TEXT}; }}
QHeaderView::section {{
    background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE};
    padding: 8px; font-size: 12px; font-weight: 700;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

/* ---------- 进度条 ---------- */
QProgressBar {{
    background: {FIELD}; border: 1px solid {LINE}; border-radius: 6px;
    text-align: center; color: {TEXT}; font-size: 12px; min-height: 16px; max-height: 16px;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT}, stop:1 {ACCENT2});
}}

/* ---------- 任务卡片/状态徽章 ---------- */
QFrame#taskCard {{
    background: {CARD}; border: 1px solid {LINE}; border-radius: 12px;
}}
QLabel#taskTitle {{ font-size: 15px; font-weight: 700; background: transparent; }}
QLabel#stageChip {{
    border-radius: 9px; padding: 3px 10px; font-size: 12px; font-weight: 700;
    background: rgba(59,130,246,0.16); color: {ACCENT2};
}}
QLabel#stageChip[tone="ok"]   {{ background: rgba(52,211,153,0.16); color: {OK}; }}
QLabel#stageChip[tone="bad"]  {{ background: rgba(248,113,113,0.16); color: {BAD}; }}
QLabel#stageChip[tone="idle"] {{ background: rgba(138,156,189,0.14); color: {MUTED}; }}
QLabel#cardMsg {{ color: {MUTED}; background: transparent; }}

/* ---------- 滚动区 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 5px; min-width: 30px; }}

/* ---------- 页头 ---------- */
QLabel#pageTitle {{ font-size: 21px; font-weight: 800; background: transparent; }}
QLabel#pageDesc {{ color: {MUTED}; font-size: 12px; background: transparent; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; background: transparent; }}
QLabel#previewName {{
    color: {ACCENT2}; font-size: 12px; background: {FIELD};
    border: 1px solid {LINE}; border-left: 3px solid {ACCENT};
    border-radius: 8px; padding: 9px 12px;
    font-family: Consolas,"Microsoft YaHei UI",monospace;
}}

/* ---------- 步骤卡片头 ---------- */
QLabel#stepBadge {{
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
    border-radius: 17px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2563eb, stop:1 {ACCENT2});
    color: white; font-size: 17px; font-weight: 800;
}}
QLabel#stepTitle {{ font-size: 16px; font-weight: 800; color: {TEXT}; background: transparent; }}
QLabel#stepSub {{ font-size: 12px; color: {MUTED}; background: transparent; }}
QFrame#stepLine {{ background: {LINE}; border: none; max-height: 1px; }}

/* ---------- 状态栏 / 对话框 ---------- */
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QMessageBox {{ background: {SURFACE}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QDialog {{ background: {SURFACE}; }}
QTextEdit {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: 8px;
             color: #c9d6ee; font-family: Consolas,monospace; font-size: 12px; }}
"""


def apply(app) -> None:
    app.setStyleSheet(build_qss())
