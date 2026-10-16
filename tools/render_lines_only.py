"""
tools/render_lines_only.py
================================
只画线路（不画站点/站名），把线路走向单独渲染出来，便于对照原图检查是否"乱"。

用法：
    python tools/render_lines_only.py [输出路径] [每像素场景单位]
"""

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication                     # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor, QBrush, QPen, QPainterPath  # noqa: E402
from PySide6.QtCore import QRectF, Qt                          # noqa: E402

from core.data_manager import get_data_manager                 # noqa: E402
from ui.metro_render import (                                   # noqa: E402
    build_smooth_path, build_rounded_polyline, build_octilinear_path,
)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (SRC_ROOT / "lines_only.png")
    mode = sys.argv[2] if len(sys.argv) > 2 else "rounded"

    app = QApplication(sys.argv)  # noqa: F841
    dm = get_data_manager()
    stations = dm.all_stations()
    lines = dm.all_lines()

    # 统计内容范围
    xs, ys = [], []
    for st in stations.values():
        xs.append(float(st.get("x", 0)))
        ys.append(float(st.get("y", 0)))
    if not xs:
        print("没有站点数据")
        return
    m = 300.0
    x0, x1 = min(xs) - m, max(xs) + m
    y0, y1 = min(ys) - m, max(ys) + m
    w, h = x1 - x0, y1 - y0

    W = 2000
    scale = W / w
    H = int(h * scale)

    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(-x0 * scale, -y0 * scale)
    p.scale(scale, scale)

    total_len = 0.0
    for ln in lines:
        seq = ln.get("stations") or []
        pts = []
        for name in seq:
            st = stations.get(name)
            if st:
                pts.append((float(st.get("x", 0)), float(st.get("y", 0))))
        if len(pts) < 2:
            continue

        from PySide6.QtCore import QPointF
        qpts = [QPointF(x, y) for x, y in pts]
        if mode == "smooth":
            path = build_smooth_path(qpts, 1.0 / 6.0)
        elif mode == "octilinear":
            path = build_octilinear_path(qpts, radius=170.0)
        else:
            path = build_rounded_polyline(qpts, radius=110.0)

        # 折线长度（用来判断有没有来回折返）
        seg = 0.0
        for i in range(1, len(pts)):
            dx = pts[i][0] - pts[i - 1][0]
            dy = pts[i][1] - pts[i - 1][1]
            seg += (dx * dx + dy * dy) ** 0.5
        total_len += seg

        pen = QPen(QColor(ln.get("color", "#888888")))
        pen.setWidthF(16.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    p.end()
    img.save(str(out))
    print(f"[OK] 已保存 {out}  ({W}x{H})  模式={mode}  线路总长≈{total_len:.0f}")


if __name__ == "__main__":
    main()
