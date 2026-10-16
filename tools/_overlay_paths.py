# -*- coding: utf-8 -*-
"""只读诊断：把「我们的线路路径 + 站点坐标」以细黑线/圈叠到原图裁剪上。
对齐了 => 黑线正好压在原图同色线中间；没对齐 => 一眼看出偏多少、往哪偏。

用法: python tools/_overlay_paths.py <x0> <y0> <x1> <y1> [outscale] [outname]
产物: logs/<outname>（默认 _overlay_zoom.png）
"""
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QBrush
from PySide6.QtCore import QRectF, Qt
from PIL import Image, ImageDraw

import importlib.util

_ARGV = list(sys.argv)
spec = importlib.util.spec_from_file_location("rc", str(SRC_ROOT / "tools" / "_render_check.py"))
rc = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0], "1", "1", "1"]
spec.loader.exec_module(rc)
sys.argv = _ARGV


def main():
    x0, y0, x1, y1 = (float(sys.argv[1]), float(sys.argv[2]),
                      float(sys.argv[3]), float(sys.argv[4]))
    outscale = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
    outname = sys.argv[6] if len(sys.argv) > 6 else "_overlay_zoom.png"
    W = int((x1 - x0) * outscale)
    H = int((y1 - y0) * outscale)

    rc.SCALE = 0.54
    app = QApplication([])   # noqa: F841
    scene = rc.build()

    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    # 只画线路：细黑线，便于压在原图上比较
    for it in scene.items():
        if it.__class__.__name__ != "MetroLineItem":
            continue
        pen = QPen(QColor(0, 0, 0, 210))
        pen.setWidthF(max(1.0, 2.0))
        pen.setCosmetic(True)
        it.setPen(pen)
    scene.render(p, QRectF(0, 0, W, H), QRectF(x0, y0, x1 - x0, y1 - y0))
    p.end()
    tmp = str(SRC_ROOT / "logs" / "_ov_tmp.png")
    img.save(tmp)

    orig = Image.open(SRC_ROOT / "assets/shenzhen_metro.png").convert("RGB").crop(
        (int(x0), int(y0), int(x1), int(y1))).resize((W, H), Image.LANCZOS)
    # 原图淡化一点，黑线更醒目
    faded = Image.blend(orig, Image.new("RGB", orig.size, (255, 255, 255)), 0.35)
    over = Image.open(tmp).convert("RGBA")
    faded = faded.convert("RGBA")
    faded.alpha_composite(over)

    # 站点坐标画小圈
    import json
    st = json.loads((SRC_ROOT / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    d = ImageDraw.Draw(faded)
    for nm, s in st.items():
        try:
            cx = (float(s["x"]) - x0) * outscale
            cy = (float(s["y"]) - y0) * outscale
        except (KeyError, TypeError, ValueError):
            continue
        if -20 <= cx <= W + 20 and -20 <= cy <= H + 20:
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(255, 0, 160), width=2)
    faded.convert("RGB").save(SRC_ROOT / "logs" / outname)
    print("saved", outname, faded.size)


main()
