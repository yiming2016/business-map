"""把程序画的线路（八向布线）以半透明叠在原图上，坐标同为原图像素，可直接核对贴合度。"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QPen
from PySide6.QtCore import QPointF, Qt
from ui.metro_render import build_octilinear_path

app = QApplication(sys.argv)
st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
lines = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))["lines"]
ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
base = np.array(ref).astype(np.float32)
base = base * 0.55 + 255 * 0.45          # 淡化原图

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
    c.setAlpha(210)
    pen = QPen(c); pen.setWidthF(14.0)
    pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawPath(build_octilinear_path(pts, 60.0))
p.end()
img.save(str(SRC / "_overlay_lines.png"))
ov = Image.open(SRC / "_overlay_lines.png")
a = np.array(ov)
m = a[:, :, 3] > 40
out = base.copy()
rgb = a[:, :, :3].astype(np.float32)
al = (a[:, :, 3:4].astype(np.float32) / 255.0)
out = base * (1 - al * m[:, :, None]) + rgb * (al * m[:, :, None])
Image.fromarray(out.astype("uint8")).resize((1400, 1400), Image.LANCZOS).save(SRC / "_overlay_v22.png")
print("saved _overlay_v22.png")
