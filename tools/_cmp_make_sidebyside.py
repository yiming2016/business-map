# -*- coding: utf-8 -*-
"""把 v2.5.1 / v2.5.2 两张实机截图拼成一张"改前 vs 改后"对比图。

用法：
    python tools/_cmp_make_sidebyside.py            # 默认裁地图区域
    python tools/_cmp_make_sidebyside.py --full     # 不裁，整窗口缩放拼接
输出：logs/_cmp_v251_vs_v252.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path(__file__).resolve().parent.parent
LOGS = SRC / "logs"

# 地图视口在整窗口截图里的位置（物理像素，标定出来的）：
#   x 起点 = 左侧图例面板右边；宽度 = 视口 874 逻辑 × dpr1.5 ≈ 1311
#   ★ 右边**收窄一点**、下边留到视口底，别把右侧面板和状态栏带进来。
CROP = (355, 95, 1608, 1298)


def load(name: str) -> Image.Image:
    p = LOGS / name
    if not p.exists():
        raise SystemExit(f"缺文件：{p}")
    return Image.open(p).convert("RGB")


def get_font(size: int):
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main() -> int:
    full = "--full" in sys.argv
    a = load("_cmp_v251.png")     # 改前
    b = load("_cmp_v252.png")     # 改后
    if not full:
        a = a.crop(CROP)
        b = b.crop(CROP)

    bar = 64
    font = get_font(34)
    W = max(a.width, b.width)
    canvas = Image.new("RGB", (W, (a.height + bar) * 2 + 8), (255, 255, 255))
    d = ImageDraw.Draw(canvas)

    y = 0
    for img, text, bg, fg in (
        (a, "改前  v2.5.1 —— 缩到默认适配 10%：整图只剩几十个站名", (192, 57, 43), (255, 255, 255)),
        (b, "改后  v2.5.2 —— 同一视角：站名几乎铺满全图", (39, 134, 74), (255, 255, 255)),
    ):
        d.rectangle([0, y, W, y + bar], fill=bg)
        d.text((16, y + 14), text, font=font, fill=fg)
        y += bar
        canvas.paste(img, (0, y))
        y += img.height + 8

    out = LOGS / "_cmp_v251_vs_v252.png"
    canvas.save(out)
    print(f"[OK] {out}  ({canvas.width}x{canvas.height})  crop={'no' if full else CROP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
