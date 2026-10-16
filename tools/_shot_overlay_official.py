# -*- coding: utf-8 -*-
"""画一张「我的线 叠在 官方原图上」的对照图，给用户**用眼睛**验收。

★ 点列不是这里自己拼的，而是 `_dump_render_polylines.py` 从
  `ui.map_view.build_line_points_ex` 导出来的（和渲染同一份代码）——
  自己再写一遍实现 ⇒ 画出来的是"我以为的样子"，不是"软件画的样子"。

用法：
    python tools/_dump_render_polylines.py _tmp_polylines.json
    python tools/_shot_overlay_official.py _tmp_polylines.json 输出.png
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OFF = ROOT / "assets" / "shenzhen_metro.png"
OUT_W = 1800


def hex2rgb(c):
    c = (c or "#808080").lstrip("#")
    if len(c) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_tmp_polylines.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "全图对照_我的线叠官方.png"
    data = json.loads(src.read_text(encoding="utf-8"))

    bg = Image.open(OFF).convert("RGB")
    s = OUT_W / float(bg.width)
    H = int(round(bg.height * s))
    bg = bg.resize((OUT_W, H), Image.LANCZOS)
    # ★ 底图压淡：不压淡的话官方线自己的颜色会盖住我画的线，看不出谁是谁
    bg = Image.blend(bg, Image.new("RGB", bg.size, (255, 255, 255)), 0.62)

    dr = ImageDraw.Draw(bg)
    for L in data:
        pts = [(p[0] * s, p[1] * s) for p in L["pts"]]
        if len(pts) < 2:
            continue
        col = hex2rgb(L.get("color"))
        dr.line(pts, fill=col, width=max(2, int(round(30 * s))), joint="curve")
    bg.save(out)
    print("[出图] %s  (%dx%d)  底图压淡 62%%  我的线宽 %dpx"
          % (out.name, OUT_W, H, max(2, int(round(30 * s)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
