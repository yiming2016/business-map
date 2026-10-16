# -*- coding: utf-8 -*-
"""只读：全量复查 —— 每个站的坐标离原图最近的白色圆点有多远。
输出 logs/_coord_check.txt。>20px 的可疑项单独列出。
注意：只查主图（y<6100），因为 y>6100 是下方那几张独立小图。
"""
import json
import math
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
CUR = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]
LJ = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
LINES = LJ["lines"]

# 主图白色斑点（放宽到 11px，含电车/云巴的小圆点）
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 10
white = ndimage.binary_erosion(white, np.ones((3, 3)))
white[6100:, 5700:] = False      # 只排除右下方那几张独立小图；蛇口一带 y 也>6100，但属于主图
lab, n = ndimage.label(white, np.ones((3, 3)))
objs = ndimage.find_objects(lab)
pts = []
for i, sl in enumerate(objs, 1):
    h = sl[0].stop - sl[0].start
    w = sl[1].stop - sl[1].start
    if h < 11 or w < 11 or max(h, w) > 90:
        continue
    if (lab[sl] == i).sum() < 90:
        continue
    pts.append(((sl[1].start + sl[1].stop) / 2, (sl[0].start + sl[0].stop) / 2, w, h))
print("主图候选圆点 %d 个" % len(pts))

FROZEN = {"坪山云巴", "有轨电车", "有轨电车支线"}
rows = []
for nm, s in CUR.items():
    x, y = float(s["x"]), float(s["y"])
    best = min(((math.hypot(px - x, py - y), px, py, pw, ph) for px, py, pw, ph in pts),
               default=(9999, 0, 0, 0, 0))
    frozen = bool(set(s["lines"]) & FROZEN)
    rows.append((best[0], nm, s["lines"], x, y, best[1], best[2], best[3], best[4], frozen))

rows.sort(key=lambda r: -r[0])
lines = ["# 坐标复查：站坐标 vs 原图最近白圆点（只看主图 y<6100）", "",
         "总共 %d 站；圆点 %d 个。" % (len(rows), len(pts)), ""]
bad = [r for r in rows if r[0] > 20 and not r[9]]
froz = [r for r in rows if r[0] > 20 and r[9]]
lines.append("## 一、地铁线站点偏移 > 20px 的（%d 个）—— 这些要修" % len(bad))
lines.append("")
lines.append("| 站名 | 所属线 | 当前坐标 | 最近圆点 | 偏移 | 圆点尺寸 |")
lines.append("|---|---|---|---|---|---|")
for d, nm, ls, x, y, px, py, pw, ph, _f in bad:
    lines.append("| %s | %s | (%d,%d) | (%d,%d) | **%.0f** | %dx%d |"
                 % (nm, "/".join(ls), x, y, px, py, d, pw, ph))
lines.append("")
lines.append("## 二、云巴/电车偏移 > 20px 的（%d 个）—— 待写坐标" % len(froz))
lines.append("")
lines.append("| 站名 | 所属线 | 当前坐标 | 最近圆点 | 偏移 |")
lines.append("|---|---|---|---|---|")
for d, nm, ls, x, y, px, py, pw, ph, _f in froz:
    lines.append("| %s | %s | (%d,%d) | (%d,%d) | %.0f |" % (nm, "/".join(ls), x, y, px, py, d))
lines.append("")
ok = [r for r in rows if r[0] <= 20]
lines.append("## 三、结论")
lines.append("")
lines.append("- 偏移 ≤20px（OK）：**%d 站**" % len(ok))
lines.append("- 偏移 >20px（地铁线，需修）：**%d 站**" % len(bad))
lines.append("- 偏移 >20px（云巴/电车，待写）：**%d 站**" % len(froz))

open(SRC + "/logs/_coord_check.txt", "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines[-8:]))
print("\n--- 偏移最大的 15 个（地铁线）---")
for d, nm, ls, x, y, px, py, pw, ph, _f in bad[:15]:
    print("  %-8s %-10s 当前(%4d,%4d) → 圆点(%4d,%4d)  偏移 %6.0f  %dx%d"
          % (nm, "/".join(ls), x, y, px, py, d, pw, ph))
