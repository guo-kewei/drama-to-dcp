"""生成应用图标 app.ico（256×256，放映机+光束+胶片造型）。"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QPainter,
                           QLinearGradient, QPen, QPixmap)

SIZE = 256


def paint() -> QPixmap:
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # 圆角深色底
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0f172a"))
    p.drawRoundedRect(QRectF(8, 8, SIZE - 16, SIZE - 16), 48, 48)

    # 放映光束（蓝色渐变，射向右侧胶片条）
    grad = QLinearGradient(60, 128, 200, 128)
    grad.setColorAt(0, QColor("#60a5fa"))
    grad.setColorAt(1, QColor("#2563eb"))
    p.setBrush(QBrush(grad))
    p.drawPolygon([QPointF(56, 92), QPointF(56, 164),
                   QPointF(196, 196), QPointF(196, 60)])

    # 放映机机身 + 镜头
    p.setBrush(QColor("#e2e8f0"))
    p.setPen(QPen(QColor("#94a3b8"), 5))
    p.drawEllipse(QRectF(28, 96, 72, 72))
    p.setBrush(QColor("#1d4ed8"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(52, 120, 24, 24))

    # 右侧胶片条（三格）
    for i, y in enumerate((60, 118, 176)):
        p.setBrush(QColor("#f8fafc") if i != 1 else QColor("#93c5fd"))
        p.drawRoundedRect(QRectF(204, y, 24, 34), 6, 6)
    p.end()
    return pm


def png_to_ico(png_bytes: bytes, ico_path: Path) -> None:
    """把 PNG 封进 ICO 容器（Vista+ 支持 PNG 负载条目）。"""
    header = struct.pack("<HHH", 0, 1, 1)              # ICONDIR
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0,       # 0 = 256px
                        1, 32, len(png_bytes), 22)     # ICONDIRENTRY
    ico_path.write_bytes(header + entry + png_bytes)


if __name__ == "__main__":
    app = QGuiApplication([])
    root = Path(__file__).resolve().parent.parent
    pm = paint()
    tmp = root / "tools" / "_icon_tmp.png"
    pm.save(str(tmp))
    png_to_ico(tmp.read_bytes(), root / "app.ico")
    tmp.unlink(missing_ok=True)
    print("app.ico 生成:", (root / "app.ico").stat().st_size, "bytes")
