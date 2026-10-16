"""
tools/locate_by_seed.py
================================
给定"大致位置"，在原图上精确定位站点标记（白底圆点/胶囊）的中心。

用在人工从图上读到大致坐标之后，把坐标精确到像素级。

用法：
    python tools/locate_by_seed.py "海上世界=1208,6645" "东角头=1603,6648" ...
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def find_marker(img, cx, cy, r=160):
    """在 (cx,cy) 附近找白底标记的中心。返回 [(x, y, 面积)] 按距离排序。"""
    y0, y1 = max(0, int(cy - r)), min(img.shape[0], int(cy + r))
    x0, x1 = max(0, int(cx - r)), min(img.shape[1], int(cx + r))
    patch = img[y0:y1, x0:x1]
    # 白：三个通道都接近 255
    white = (patch.min(axis=2) >= 235)
    lab, n = ndimage.label(white, structure=np.ones((3, 3), int))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        area = len(ys)
        if area < 180:
            continue
        w = xs.max() - xs.min() + 1
        h = ys.max() - ys.min() + 1
        fill = area / (w * h)
        if fill < 0.62 or max(w, h) > 70:
            continue
        mx = x0 + (xs.min() + xs.max()) / 2
        my = y0 + (ys.min() + ys.max()) / 2
        d = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
        out.append((d, round(mx, 1), round(my, 1), area, w, h))
    out.sort()
    return out


def main():
    SRC = Path(__file__).resolve().parent.parent
    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))
    st_path = SRC / "data" / "stations.json"
    doc = json.loads(st_path.read_text(encoding="utf-8"))
    st = doc["stations"]

    print(f"{'站点':<10}{'种子':<20}{'找到的标记（距离/坐标/面积/宽高）'}")
    print("-" * 90)
    for a in sys.argv[1:]:
        name, _, pos = a.partition("=")
        cx, cy = (float(v) for v in pos.split(","))
        hits = find_marker(img, cx, cy)
        print(f"{name:<10}({cx:.0f},{cy:.0f})".ljust(30), end="")
        if not hits:
            print("  ✗ 附近没有标记")
            continue
        for h in hits[:3]:
            print(f"  d={h[0]:>5.0f} ({h[1]},{h[2]}) area={h[3]} {h[4]}×{h[5]}", end="")
        print()
        d, mx, my, *_ = hits[0]
        if name in st:
            old = (st[name]["x"], st[name]["y"])
            st[name]["x"] = mx
            st[name]["y"] = my
            print(f"{'':<30}  ↳ 写入 {name}: {old} → ({mx}, {my})")

    st_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n[OK] 已更新 stations.json")


if __name__ == "__main__":
    main()
