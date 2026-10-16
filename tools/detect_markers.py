"""从原图中检测"站点标记"（白底圆点 / 圆角胶囊），并输出标记周围的主要线路色。

原理：
  站点标记 = 一块小白斑，四周被彩色线 / 深色描边包围。
  把非白像素当墨迹 -> 白像素连通域 -> 被墨迹包围的小白块 = 候选站标。

关键：**换乘站的胶囊标记比普通站的圆点大得多**（实测可达 88x38），
      早期版本把 MAX_SIDE 设成 60，结果所有大胶囊都被滤掉，
      换乘站只能去抢隔壁普通站的圆点 —— 这是坐标错位的根源之一。

用法：
    python tools/detect_markers.py            # 统计 + 叠加图
    python tools/detect_markers.py --dump     # 导出 data/markers.json
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
ORIGINAL = SRC / "assets" / "shenzhen_metro.png"

# 地图主体区域（排除标题、图例、二维码）
REGION = (100, 600, 7920, 7150)
# 右下角两张附图（有轨电车 / 坪山云巴）不参与主图站标检测
INSET_EXCLUDE = (5620, 6050, 7920, 7150)

MIN_AREA, MAX_AREA = 120, 14000
MIN_SIDE, MAX_SIDE = 11, 110
WHITE_MIN = 222
MIN_FILL = 0.55


def main():
    dump = "--dump" in sys.argv
    img = Image.open(ORIGINAL).convert("RGB")
    L, T, R, B = REGION
    sub = img.crop((L, T, R, B))
    a = np.asarray(sub).astype(np.int16)
    print(f"工作区域: {sub.size}")

    ink = a.min(axis=2) < WHITE_MIN
    white = ~ink
    lab, n = ndimage.label(white)
    print(f"白斑连通域总数: {n}")

    # 排除附图区域
    ex0, ey0, ex1, ey1 = INSET_EXCLUDE
    objs = ndimage.find_objects(lab)
    cands = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
            continue
        area = int((lab[sl] == i).sum())
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        cx = sl[1].start + w / 2 + L
        cy = sl[0].start + h / 2 + T
        if ex0 <= cx <= ex1 and ey0 <= cy <= ey1:
            continue
        m = (lab[sl] == i)
        patch = a[sl]
        if patch[m].min(axis=1).mean() < WHITE_MIN:
            continue
        fill = area / float(w * h)
        # 斜置的换乘胶囊（例如赤湾）轴对齐包围盒填充率只有 ~0.5，
        # 所以大块放宽阈值，小块（文字空洞）仍要求高填充率
        min_fill = 0.42 if max(w, h) >= 36 else MIN_FILL
        if fill < min_fill:
            continue
        cands.append({
            "x": round(float(cx), 1), "y": round(float(cy), 1),
            "w": int(w), "h": int(h), "area": area, "fill": round(float(fill), 3),
        })

    print(f"形状/尺寸筛选后候选: {len(cands)}")
    fills = sorted(c["fill"] for c in cands)
    if fills:
        print(f"  填充率 中位={fills[len(fills)//2]:.3f}")

    solid = cands
    big = [c for c in solid if max(c["w"], c["h"]) > 58]
    print(f"  实心白块: {len(solid)}   其中大号（胶囊，边长>58）: {len(big)}")

    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    print(f"我的站点数: {len(st)}")

    # 我的坐标覆盖了多少个检测到的标记
    used = set()
    for s in st.values():
        best, bd = -1, 1e18
        for i, c in enumerate(solid):
            d = (c["x"] - s["x"]) ** 2 + (c["y"] - s["y"]) ** 2
            if d < bd:
                bd, best = d, i
        if bd ** 0.5 <= 45:
            used.add(best)
    print(f"  我的坐标落在检测标记上（<=45px）的站: {len(used)} / {len(st)}")
    print(f"  未被任何站占用的标记: {len(solid) - len(used)}")

    side = 1800
    k = side / img.size[0]
    vis = img.resize((side, side), Image.LANCZOS)
    d = ImageDraw.Draw(vis)
    for i, c in enumerate(solid):
        x, y = c["x"] * k, c["y"] * k
        col = (0, 170, 0) if i in used else (255, 0, 255)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=col, width=2)
    vis.save(str(SRC / "markers_vis.png"))
    print(f"[OK] 叠加图 -> {SRC / 'markers_vis.png'}  (绿=已被占用, 品红=空闲标记)")

    if dump:
        p = DATA / "markers.json"
        p.write_text(json.dumps({"markers": solid}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[OK] 已导出 {p}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
