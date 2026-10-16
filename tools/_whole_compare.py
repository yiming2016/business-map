# -*- coding: utf-8 -*-
"""只读：整图上下对照（上=我们的渲染，下=原图同区域）。
用法: python tools/_whole_compare.py [outwidth] [viewscale]
"""
import sys
from pathlib import Path
SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtCore import QRectF
from PIL import Image, ImageDraw, ImageFont

import importlib.util
_ARGV = list(sys.argv)
spec = importlib.util.spec_from_file_location("rc", str(SRC_ROOT / "tools" / "_render_check.py"))
rc = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0], "1", "1", "1"]
spec.loader.exec_module(rc)
sys.argv = _ARGV

def main():
    W = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
    VS = float(sys.argv[2]) if len(sys.argv) > 2 else 0.54
    rc.SCALE = VS
    rc.OUT = 1.0
    app = QApplication([])
    scene = rc.build()
    br = scene.itemsBoundingRect()
    X0, Y0, X1, Y1 = 355.0, 712.0, 7825.0, 6937.0
    if len(sys.argv) >= 6:
        X0, Y0, X1, Y1 = (float(sys.argv[3]), float(sys.argv[4]),
                          float(sys.argv[5]), float(sys.argv[6]))
    OUT_NAME = sys.argv[7] if len(sys.argv) > 7 else "_whole_compare.png"
    H = int(W * (Y1 - Y0) / (X1 - X0))
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    scene.render(p, QRectF(0, 0, W, H), QRectF(X0, Y0, X1 - X0, Y1 - Y0))
    p.end()
    _p = str(SRC_ROOT / "logs" / "_whole_tmp.png")
    ok = img.save(_p)
    print("save", ok, "null", img.isNull(), "size", W, H, "->", _p)
    if not ok:
        raise SystemExit("QImage 保存失败")
    mine = Image.open(_p).convert("RGB")
    orig = Image.open(SRC_ROOT / "assets/shenzhen_metro.png").convert("RGB").crop(
        (int(X0), int(Y0), int(X1), int(Y1))).resize((W, H), Image.LANCZOS)
    try:
        fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
    except Exception:
        fnt = ImageFont.load_default()
    T = 34
    sheet = Image.new("RGB", (W, H * 2 + T * 2 + 8), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((8, 4), "我们的渲染", fill=(10, 10, 10), font=fnt)
    sheet.paste(mine, (0, T))
    d.text((8, T + H + 6), "原图", fill=(10, 10, 10), font=fnt)
    sheet.paste(orig, (0, T * 2 + H + 8))
    sheet.save(SRC_ROOT / "logs" / OUT_NAME)
    print("saved", OUT_NAME, sheet.size)

main()
