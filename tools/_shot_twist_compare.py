# -*- coding: utf-8 -*-
"""局部放大对照：官方原图（压淡） + 「修复前」的线 + 「修复后」的线。

用户原话：「很多地方都有奇怪的扭曲」+ 一张截图。
修完之后要能**用眼睛**确认：修复后的线是不是真的趴在官方那条线上。

修复前/后的点列分别来自两次 `_dump_render_polylines.py`（同一份渲染代码），
不是这里自己拼的 —— 自己拼一遍就会"改坏了也看不出来"。

用法：
    python tools/_shot_twist_compare.py <cx> <cy> <half> <输出.png> [标题]
例：
    python tools/_shot_twist_compare.py 2560 2020 320 扭曲_13号线光明城德雅路.png "13号线 光明城→德雅路"
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OFF = ROOT / "assets" / "shenzhen_metro.png"
AFTER = ROOT / "_tmp_polylines.json"
BEFORE = ROOT / "_tmp_polylines_before.json"
OUT_W = 900


def hex2rgb(c):
    c = (c or "#808080").lstrip("#")
    if len(c) != 6:
        return (128, 128, 128)
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def draw(dr, data, s, cx, cy, half, col, width, only_near=None):
    """只画落在窗口附近的线（整图 20 条线，全画会糊）。"""
    for L in data:
        pts = [(p[0], p[1]) for p in L["pts"]]
        if len(pts) < 2:
            continue
        if only_near:
            near = any(abs(x - cx) < half * 1.6 and abs(y - cy) < half * 1.6
                       for x, y in pts)
            if not near:
                continue
        P = [((x - (cx - half)) * s, (y - (cy - half)) * s) for x, y in pts]
        dr.line(P, fill=col, width=width, joint="curve")
        for x, y in P:
            dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)


def main():
    cx, cy, half = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "_twist.png"
    title = sys.argv[5] if len(sys.argv) > 5 else ""

    bg = Image.open(OFF).convert("RGB").crop(
        (int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
    s = OUT_W / float(bg.width)
    H = int(round(bg.height * s))
    W = OUT_W
    bg = bg.resize((W, H), Image.LANCZOS)
    # 底图压淡：不压淡的话官方线自己的颜色会盖住我画的线
    bg = Image.blend(bg, Image.new("RGB", bg.size, (255, 255, 255)), 0.55)
    dr = ImageDraw.Draw(bg)

    before = json.loads(BEFORE.read_text(encoding="utf-8")) if BEFORE.exists() else []
    after = json.loads(AFTER.read_text(encoding="utf-8")) if AFTER.exists() else []
    draw(dr, before, s, cx, cy, half, (30, 90, 220), max(2, int(5 * s * 4)), True)
    draw(dr, after, s, cx, cy, half, (225, 40, 40), max(2, int(7 * s * 4)), True)

    # 图例
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    except Exception:
        f = ImageFont.load_default()
    ly = 12
    for col, txt in (((225, 40, 40), "修复后（v2.6.63）"),
                     ((30, 90, 220), "修复前（八向化）")):
        dr.rectangle([12, ly, 34, ly + 16], fill=col)
        dr.text((42, ly - 2), txt, fill=(20, 20, 20), font=f)
        ly += 26
    if title:
        dr.text((12, ly + 4), title, fill=(20, 20, 20), font=f)
    bg.save(str(out))
    print("[出图]", out, bg.size)


if __name__ == "__main__":
    main()
