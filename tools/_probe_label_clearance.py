# -*- coding: utf-8 -*-
"""量原图：站名离**线路中心**有多远（用来定"站名至少要让开线宽"这个下限）。

做法：在站点正上方/正下方扫一条竖线（站点在线上的常见情形），
      找出第一块/最后一块**深色文字**像素，算它到站心的距离。
      再减去线宽的一半 ⇒ 就是"站名边缘离线的净空"。
"""
import json, math, os, sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_text(c):
    return max(c) < 120          # 站名是近黑的深灰 #111827 一类


def main(names):
    im = Image.open(os.path.join(ROOT, "assets", "shenzhen_metro.png")).convert("RGB")
    px = im.load()
    with open(os.path.join(ROOT, "data", "stations.json"), encoding="utf-8") as f:
        sts = list(json.load(f)["stations"].values())
    m = {s["station_name"]: s for s in sts}
    print("线宽的一半 = 11（原图实测）")
    print(f"{'站名':<12}{'向上最近文字':>12}{'向下最近文字':>12}{'净空(近侧)':>12}")
    rows = []
    for nm in names:
        s = m.get(nm)
        if not s:
            continue
        cx, cy = int(s["x"]), int(s["y"])
        up = dn = None
        for d in range(20, 130):
            if up is None and is_text(px[cx, cy - d]):
                up = d
            if dn is None and is_text(px[cx, cy + d]):
                dn = d
            if up is not None and dn is not None:
                break
        near = min([v for v in (up, dn) if v is not None], default=None)
        clearance = (near - 11) if near is not None else None
        rows.append(clearance)
        print(f"{nm:<12}{str(up):>12}{str(dn):>12}{str(clearance):>12}")
    rows = [r for r in rows if r is not None]
    if rows:
        rows.sort()
        print("\n净空分布：min %d / 中位 %d / max %d（共 %d 站）"
              % (rows[0], rows[len(rows) // 2], rows[-1], len(rows)))


if __name__ == "__main__":
    main(sys.argv[1:] or ["莲塘", "梧桐山南", "清湖", "湖贝", "老街", "国贸", "大剧院",
                          "华强路", "科学馆", "岗厦", "会展中心"])
