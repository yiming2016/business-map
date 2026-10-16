"""把程序画的线路半透明叠在原图上，并按指定区域输出放大裁剪图，用于核对贴合度。

用法:
  python tools/overlay_zoom.py                 # 输出全图 _ov_full.png（原图 1/4）
  python tools/overlay_zoom.py x0 y0 x1 y1 [scale] [outname]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor, QPen  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from ui.metro_render import build_octilinear_path  # noqa: E402

CACHE = SRC / "_ov_cache.png"


def build_overlay():
    app = QApplication.instance() or QApplication(sys.argv)
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))["lines"]
    ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
    W, H = ref.size
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    for ln in lines:
        pts = []
        for n in (ln.get("stations") or []):
            s = st.get(n)
            if s:
                pts.append(QPointF(float(s["x"]), float(s["y"])))
        if len(pts) < 2:
            continue
        c = QColor(ln.get("color", "#888888"))
        c.setAlpha(180)
        pen = QPen(c)
        pen.setWidthF(16.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(build_octilinear_path(pts, 60.0))
    p.end()
    img.save(str(SRC / "_ov_lines_only.png"))
    _ = app

    a = np.array(Image.open(SRC / "_ov_lines_only.png"))
    base = np.array(ref).astype(np.float32) * 0.55 + 255 * 0.45
    al = a[:, :, 3:4].astype(np.float32) / 255.0
    m = a[:, :, 3] > 40
    out = base * (1 - al * m[:, :, None] * 0.92) + a[:, :, :3].astype(np.float32) * (al * m[:, :, None] * 0.92)
    Image.fromarray(out.astype("uint8")).save(CACHE)
    print(f"[OK] 全图叠加 -> {CACHE}")


def crop(x0, y0, x1, y1, scale=1.0, out="_ov_zoom.png"):
    im = Image.open(CACHE).convert("RGB").crop((int(x0), int(y0), int(x1), int(y1)))
    if scale != 1.0:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    im.save(SRC / out)
    print(f"[OK] -> {SRC / out}  {im.size}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    build_overlay()
    if len(args) >= 4:
        sc = float(args[4]) if len(args) > 4 else 1.0
        nm = args[5] if len(args) > 5 else "_ov_zoom.png"
        crop(float(args[0]), float(args[1]), float(args[2]), float(args[3]), sc, nm)
    else:
        Image.open(CACHE).resize((1500, 1500), Image.LANCZOS).save(SRC / "_ov_full.png")
        print(f"[OK] -> {SRC / '_ov_full.png'}")
    _ = ImageDraw
