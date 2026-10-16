# -*- coding: utf-8 -*-
"""只读：清点原图主图里所有「胶囊/药丸」的**方向**（横 / 竖 / 斜 45°）。
用连通域的二阶矩算主轴角度，并按实心度过滤掉文字块。
产物 logs/_pill_census.txt
"""
import json
import math
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]

white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 10
white = ndimage.binary_erosion(white, np.ones((3, 3)))
white[6100:, 5700:] = False          # 排除右下角那几张独立小图
lab, n = ndimage.label(white, np.ones((3, 3)))
objs = ndimage.find_objects(lab)

rows = []
for i, sl in enumerate(objs, 1):
    if sl is None:
        continue
    m = (lab[sl] == i)
    area = int(m.sum())
    h = sl[0].stop - sl[0].start
    w = sl[1].stop - sl[1].start
    if area < 300 or max(w, h) > 140 or min(w, h) < 14:
        continue
    fill = area / (w * h)
    if fill < 0.72:                   # 文字笔画的实心度低，排除
        continue
    ys, xs = np.where(m)
    cx = xs.mean() + sl[1].start
    cy = ys.mean() + sl[0].start
    # 主轴方向（协方差矩阵最大特征值的方向）
    cov = np.cov(np.stack([xs, ys]))
    ev, evec = np.linalg.eigh(cov)
    ang = math.degrees(math.atan2(evec[0, -1], evec[1, -1])) % 180   # 0=竖(沿y) 90=横
    # 换成"图形长轴与水平线的夹角"：长轴向量 (evec[0,-1](x), evec[1,-1](y))
    vx, vy = evec[0, -1], evec[1, -1]
    deg = math.degrees(math.atan2(vy, vx)) % 180    # 0=水平, 90=竖直
    elong = math.sqrt(ev[-1]) / max(math.sqrt(ev[0]), 1e-6)
    rows.append((cx, cy, w, h, area, fill, deg, elong))


def klass(deg, elong):
    if elong < 1.45:
        return "圆/方"
    d = deg % 180
    if d <= 22.5 or d >= 157.5:
        return "横"
    if 67.5 <= d <= 112.5:
        return "竖"
    return "斜(45°附近)"


# 匹配最近站点
def nearest(cx, cy):
    best, bn = 1e9, ""
    for nm, s in ST.items():
        d = math.hypot(float(s["x"]) - cx, float(s["y"]) - cy)
        if d < best:
            best, bn = d, nm
    return bn, best

rows.sort(key=lambda r: r[6])
out = ["# 原图胶囊方向清点（主图）", "",
       "共 %d 个（实心度≥0.72，尺寸 14~140）" % len(rows), ""]
from collections import Counter
cnt = Counter(klass(r[6], r[7]) for r in rows)
out.append("## 方向分布")
out.append("")
for k in ("横", "竖", "斜(45°附近)", "圆/方"):
    out.append("- **%s**：%d 个" % (k, cnt.get(k, 0)))
out.append("")
out.append("## 明细（按方向分组，只列实心拉长的前 40 个）")
out.append("")
for k in ("横", "竖", "斜(45°附近)"):
    sub = [r for r in rows if klass(r[6], r[7]) == k]
    out.append("### %s（%d 个）" % (k, len(sub)))
    out.append("")
    out.append("| 中心 | 包围盒 | 主轴角 | 长宽比 | 最近站(距离) | 该站线路 |")
    out.append("|---|---|---|---|---|---|")
    for cx, cy, w, h, area, fill, deg, elong in sub[:40]:
        nm, d = nearest(cx, cy)
        ls = "/".join(ST[nm]["lines"]) if nm in ST else "?"
        out.append("| (%d,%d) | %dx%d | %.0f° | %.2f | %s(%.0f) | %s |"
                   % (cx, cy, w, h, deg, elong, nm, d, ls))
    out.append("")

open(SRC + "/logs/_pill_census.txt", "w", encoding="utf-8").write("\n".join(out))
for line in out[:14]:
    print(line)
