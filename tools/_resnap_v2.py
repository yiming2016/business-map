# -*- coding: utf-8 -*-
"""阶段1（只读，v2）：保守吸附重取坐标。

改法（相对 v1 的失败）：
 - v1 用全局匈牙利一对一，结果被图例区噪声圆点抢走 → 连锁错配（140 站位移>45px）
 - v2：**只对 60px 内找到圆点的站做吸附**，找不到就保持原坐标并标出来人工处理
   → 不产生连锁错误，可审计

圆点有效性三条硬门槛：
  1) 位于线路图包围盒内（由站点表坐标外扩 200px 估算）
  2) 圆点（含 bbox 外扩 3px）必须**贴到至少一条线色走廊**（≤22px）
  3) 形态：面积≥150、边长 14~140、填充率≥0.55

输出：logs/重取坐标_v2.md（分线表）+ logs/_resnap_v2.json
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _l}

# ★ 实测色覆盖（lines.json 里记错会直接导致整条线吸附失败）
COLOR_OVERRIDE = {"4": "#E71615", "11": "#6D2041"}
for k, v in COLOR_OVERRIDE.items():
    if k in COLOR:
        print(f"  [色覆盖] {k}号线 {COLOR[k]} -> {v}（实测）")
        COLOR[k] = v

SNAP_R = 150   # 吸附半径（放大到 150 以覆盖成片漂移的云巴/有轨电车）


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------- 包围盒 ----------
xs = [s["x"] for s in ST.values()]; ys = [s["y"] for s in ST.values()]
BX = (min(xs) - 250, max(xs) + 250, min(ys) - 250, max(ys) + 250)
print(f"线路图包围盒 x[{BX[0]:.0f},{BX[1]:.0f}] y[{BX[2]:.0f},{BX[3]:.0f}]")

# ---------- 走廊距离场 ----------
DF = {}
for lid, c in COLOR.items():
    r, g, b = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    m = ndimage.binary_erosion(m, np.ones((3, 3)))
    DF[lid] = ndimage.distance_transform_edt(~m)

# ---------- 圆点 ----------
white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
area = np.bincount(lab.ravel())
sl = ndimage.find_objects(lab)
raw = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 150:
        continue
    h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
    if not (14 <= w <= 140 and 14 <= h <= 140):
        continue
    if a / (w * h) < 0.55:
        continue
    sub = lab[s] == i
    yy, xx = np.nonzero(sub)
    raw.append({"cx": int(xx.mean()) + s[1].start, "cy": int(yy.mean()) + s[0].start,
                "w": w, "h": h, "x0": s[1].start, "y0": s[0].start, "x1": s[1].stop, "y1": s[0].stop})
print(f"形态候选 {len(raw)} 个")


def touch(c):
    """返回 {线: 最小距离}（只保留 ≤22px 的）"""
    out = {}
    for lid in COLOR:
        f = DF[lid]
        d = min(float(f[c["cy"], c["cx"]]),
                float(f[max(0, c["y0"] - 3):c["y1"] + 3, max(0, c["x0"] - 3):c["x1"] + 3].min()))
        if d <= 22:
            out[lid] = round(d, 1)
    return out


circ = []
for c in raw:
    if not (BX[0] <= c["cx"] <= BX[1] and BX[2] <= c["cy"] <= BX[3]):
        c["drop"] = "包围盒外"
        continue
    t = touch(c)
    if not t:
        c["drop"] = "不贴任何线"
        continue
    c["touch"] = t
    circ.append(c)
print(f"有效圆点 {len(circ)} 个（剔除 {len(raw)-len(circ)} 个：包围盒外/不贴线）")

# ---------- 保守吸附：60px 内、一对一（按距离从小到大贪心） ----------
pairs = []
for nm, s in ST.items():
    own = set(s["lines"])
    for j, c in enumerate(circ):
        d = ((s["x"] - c["cx"]) ** 2 + (s["y"] - c["cy"]) ** 2) ** 0.5
        if d <= SNAP_R and (own & set(c["touch"])):   # 圆点必须贴本站所属线之一
            pairs.append((d, nm, j))
pairs.sort()
used_c, used_s, assign = set(), set(), {}
for d, nm, j in pairs:
    if nm in used_s or j in used_c:
        continue
    assign[nm] = (j, d)
    used_s.add(nm); used_c.add(j)

print(f"吸附成功 {len(assign)} / {len(ST)} 站；未吸附 {len(ST)-len(assign)} 站")

# ---------- 输出 ----------
out = ["# 阶段1 v2：按原图圆点重取坐标（只读，未写入业务数据）", "",
       "口径：圆点必须①在图包围盒内 ②贴到≥1条线色走廊(≤22px) ③形态达标；"
       "站点只吸附 60px 内最近的圆点，且一对一。", "",
       f"有效圆点 {len(circ)} 个；吸附成功 {len(assign)} 站；未吸附 {len(ST)-len(assign)} 站。", ""]
out.append("## 未吸附（保持原坐标，需人工看图定位）")
out.append("| 站名 | 原坐标 | 所属线 |")
out.append("|---|---|---|")
for nm in sorted(set(ST) - set(assign)):
    out.append(f"| {nm} | ({ST[nm]['x']:.0f},{ST[nm]['y']:.0f}) | {'/'.join(ST[nm]['lines'])} |")
out.append("")
mv = sorted(((assign[k][1], k) for k in assign), reverse=True)
out.append(f"## 位移 >20px 的站（{sum(1 for d,_ in mv if d>20)} 个，供重点复核）")
out.append("| 站名 | 原坐标 | 新坐标 | 位移 | 圆点 | 贴线 |")
out.append("|---|---|---|---|---|---|")
for d, nm in mv:
    if d <= 20:
        break
    j, _ = assign[nm]
    c = circ[j]
    out.append(f"| {nm} | ({ST[nm]['x']:.0f},{ST[nm]['y']:.0f}) | ({c['cx']},{c['cy']}) | {d:.0f}px | "
               f"{c['w']}×{c['h']} | {'/'.join(c['touch'])} |")

for lid in COLOR:
    seq = ORDER.get(lid) or []
    if not seq:
        continue
    out.append("")
    out.append(f"## {lid}号线（{COLOR[lid]}） {len(seq)} 站")
    out.append("| # | 站名 | 原坐标 | 新坐标 | 位移 | 圆点 | 形态 | 贴本线 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for i, nm in enumerate(seq, 1):
        s = ST.get(nm)
        if nm in assign:
            j, d = assign[nm]
            c = circ[j]
            kind = "药丸" if min(c["w"], c["h"]) >= 30 else "正圆"
            dl = c["touch"].get(lid)
            flag = "✅" if dl is not None and dl <= 22 else (f"⚠️{dl:.0f}" if dl is not None else "❌")
            out.append(f"| {i} | {nm} | ({s['x']:.0f},{s['y']:.0f}) | ({c['cx']},{c['cy']}) | "
                       f"{d:.0f}px | {c['w']}×{c['h']} | {kind} | {flag} |")
        else:
            out.append(f"| {i} | {nm} | ({s['x']:.0f},{s['y']:.0f}) | 未吸附 | — | — | — | — |")

open(SRC + "/logs/重取坐标_v2.md", "w", encoding="utf-8").write("\n".join(out))
json.dump({k: {"old": [ST[k]["x"], ST[k]["y"]],
               "new": [circ[v[0]]["cx"], circ[v[0]]["cy"]], "move": round(v[1], 1)}
          for k, v in assign.items()},
          open(SRC + "/logs/_resnap_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写出 logs/重取坐标_v2.md 与 logs/_resnap_v2.json")
