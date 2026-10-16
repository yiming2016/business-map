"""
tools/compare_layout.py
================================
把"程序画的线路"与"原图"按同一坐标系半透明叠加，
一眼看出布局对不对得上（这是检验"对照图片"最直接的办法）。

用法：
    python tools/compare_layout.py [输出路径] [叠加图边长]
"""

import sys
import json
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PIL import Image                                  # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor, QPen  # noqa: E402
from PySide6.QtCore import Qt, QPointF                 # noqa: E402

from core.data_manager import get_data_manager         # noqa: E402
from ui.metro_render import build_rounded_polyline     # noqa: E402

Image.MAX_IMAGE_PIXELS = None
ORIGINAL = SRC_ROOT / "assets" / "shenzhen_metro.png"
SCENE = 8000.0


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (SRC_ROOT / "compare.png")
    side = int(sys.argv[2]) if len(sys.argv) > 2 else 1600
    k = side / SCENE

    app = QApplication(sys.argv)  # noqa: F841
    dm = get_data_manager()
    stations = dm.all_stations()
    lines = dm.all_lines()

    # 程序画的线（透明底）
    layer = QImage(side, side, QImage.Format_ARGB32)
    layer.fill(QColor(0, 0, 0, 0))
    p = QPainter(layer)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(k, k)
    for ln in lines:
        seq = ln.get("stations") or []
        pts = []
        for name in seq:
            st = stations.get(name)
            if st:
                pts.append(QPointF(float(st["x"]), float(st["y"])))
        if len(pts) < 2:
            continue
        path = build_rounded_polyline(pts, radius=110.0)
        pen = QPen(QColor(ln.get("color", "#888888")))
        pen.setWidthF(9.0 / k * 1.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.end()
    layer.save(str(SRC_ROOT / "_mylines_layer.png"))

    # 原图淡化
    ref = Image.open(ORIGINAL).convert("RGB").resize((side, side), Image.LANCZOS)
    ref = Image.blend(ref, Image.new("RGB", (side, side), (255, 255, 255)), 0.55)

    # 叠加
    my = Image.open(str(SRC_ROOT / "_mylines_layer.png")).convert("RGBA")
    ref = ref.convert("RGBA")
    ref.alpha_composite(my)
    ref.convert("RGB").save(str(out))
    print(f"[OK] 叠加对照图 → {out} ({side}x{side})")


if __name__ == "__main__":
    main()
