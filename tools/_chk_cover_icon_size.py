# -*- coding: utf-8 -*-
"""给"添加图片"图标做像素体检：数一下不透明像素占多大范围。

用来判断"按钮变大了、但图标看起来还是小"是图标本身留白过多，还是尺寸没生效。

用法：python tools/_chk_cover_icon_size.py
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication                       # noqa: E402
from ui.widgets import make_add_image_icon                       # noqa: E402

app = QApplication(sys.argv)


def probe(size: int) -> None:
    pm = make_add_image_icon(size).pixmap(size, size)
    img = pm.toImage()
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                xs.append(x)
                ys.append(y)
    if not xs:
        print(f"size={size}: 全透明（没画出东西）")
        return
    bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    print(f"size={size}: 画布 {img.width()}x{img.height()}  "
          f"实际内容 {bw}x{bh}  占画布 {bw / size:.0%} x {bh / size:.0%}")


for s in (30, 34, 66, 76):
    probe(s)

out = SRC / "logs" / "_icon_probe_66.png"
make_add_image_icon(66).pixmap(66, 66).save(str(out))
print("saved", out)
