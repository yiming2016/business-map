# -*- coding: utf-8 -*-
"""只读：把原图的一小块打成**字符画**，让"看不了图"的环境也能判形状。

用法: python tools/_ascii_view.py <cx> <cy> <half> [step]
  step = 每个字符代表几个原图像素（默认 6；越小越清楚但越宽）
字符含义：
  ' ' 白底      '.' 浅灰(文字抗锯齿边)      'k' 黑字
  '1'..'9','A'..'K' 各线路色（下面打图例）
  '?' 其它有颜色的
★ 用它判断"原图这里到底画了个啥"（号码方块/胶囊/圆点/虚线）。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from core.data_manager import get_data_manager          # noqa: E402


def hex2rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def main():
    cx, cy = int(sys.argv[1]), int(sys.argv[2])
    half = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    step = int(sys.argv[4]) if len(sys.argv) > 4 else 6

    dm = get_data_manager()
    pal = []           # (char, rgb, name)
    chars = "123456789ABCDEFGHIJK"
    for i, line in enumerate(dm.all_lines()):
        if i >= len(chars):
            break
        pal.append((chars[i], hex2rgb(line.get("color", "#888888")), str(line.get("id"))))
    pal.append(("k", (0x23, 0x1F, 0x20), "黑字"))
    pal.append((".", (0x8B, 0x8B, 0x8C), "灰虚线"))

    img = np.asarray(Image.open(SRC / "assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(W, cx + half), min(H, cy + half)
    sub = img[y0:y1, x0:x1]
    h, w = sub.shape[:2]
    nh, nw = h // step, w // step
    sub = sub[:nh * step, :nw * step].reshape(nh, step, nw, step, 3)
    # 每格取"最常见颜色"太慢，直接取中心像素 + 判断该格里有没有黑字
    cen = sub[:, step // 2, :, step // 2, :]           # (nh,nw,3)
    dark = (sub.sum(axis=3) < 300).sum(axis=(1, 3))    # 黑像素计数

    rows = []
    for j in range(nh):
        line = []
        for i in range(nw):
            r, g, b = cen[j, i]
            best, bd = " ", 1e9
            for ch, (pr, pg, pb), _nm in pal:
                d = abs(r - pr) + abs(g - pg) + abs(b - pb)
                if d < bd:
                    bd, best = d, ch
            if bd > 90:
                # 不是白底也不是任何已知色
                best = "?" if (abs(r - 255) + abs(g - 255) + abs(b - 255)) > 90 else " "
            if dark[j, i] >= 2 and best == " ":
                best = "k"
            line.append(best)
        rows.append("".join(line))

    print("区域 (%d,%d)±%d  每字符 %dpx  原图坐标 x:%d..%d y:%d..%d"
          % (cx, cy, half, step, x0, x1, y0, y1))
    print("图例: " + "  ".join("%s=%s" % (ch, nm) for ch, _c, nm in pal)
          + "  空格=白底  ?=其它色")
    for j, r in enumerate(rows):
        print("%4d|%s" % (y0 + j * step, r))


if __name__ == "__main__":
    main()
