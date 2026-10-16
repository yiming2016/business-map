"""
tools/analyze_image_colors.py
========================
分析深圳地铁原图的颜色分布，为"站点吸附到线路"做准备。

输出：
  - 图片基本信息
  - 主要颜色 TOP 30（排除近白/近黑/近灰）
  - 与 16 条线路官方色的匹配情况
"""

import json
from collections import Counter
from pathlib import Path

from PIL import Image

SRC_ROOT = Path(__file__).resolve().parent.parent
IMG_PATH = SRC_ROOT / "assets" / "shenzhen_metro.png"
LINES_PATH = SRC_ROOT / "data" / "lines.json"


def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def main():
    img = Image.open(IMG_PATH)
    print(f"原图: {img.size} {img.mode}")

    # 缩到 1000x1000 做统计（样本足够）
    small = img.convert("RGB").resize((1000, 1000), Image.NEAREST)
    px = list(small.getdata())

    print(f"\n=== 像素总数(采样) {len(px)} ===")

    # 量化到每通道 16 级，减少噪声
    def quant(c):
        return tuple((v // 16) * 16 + 8 for v in c)

    q = Counter(quant(p) for p in px)

    def is_grayish(c, tol=28):
        r, g, b = c
        mx, mn = max(c), min(c)
        return (mx - mn) < tol

    def is_extreme(c, lo=40, hi=225):
        return all(v < lo for v in c) or all(v > hi for v in c)

    print("\n=== 主要彩色（排除灰/白/黑）TOP 30 ===")
    n = 0
    top_colors = []
    for color, cnt in q.most_common(500):
        if is_grayish(color) or is_extreme(color):
            continue
        top_colors.append((color, cnt))
        print(f"  #{color[0]:02X}{color[1]:02X}{color[2]:02X}  {cnt:>7}  ({cnt/len(px)*100:.2f}%)")
        n += 1
        if n >= 30:
            break

    # 与线路官方色匹配
    print("\n=== 与 16 条线路官方色的匹配 ===")
    with open(LINES_PATH, "r", encoding="utf-8") as f:
        lines = json.load(f)["lines"]

    for line in lines:
        official = hex_to_rgb(line["color"])
        best = None
        best_d = 1e9
        total_near = 0
        for color, cnt in q.items():
            d = sum((a - b) ** 2 for a, b in zip(official, color)) ** 0.5
            if d < best_d:
                best_d = d
                best = (color, cnt)
            if d < 40:
                total_near += cnt
        bh = f"#{best[0][0]:02X}{best[0][1]:02X}{best[0][2]:02X}" if best else "?"
        print(f"  线路{line['id']:>2} ({line['alias']})  官方={line['color']}"
              f"  最接近={bh} 距离={best_d:.0f}  近似像素={total_near}")


if __name__ == "__main__":
    main()
