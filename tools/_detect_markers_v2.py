# -*- coding: utf-8 -*-
"""圆点检测器 v2（只读）：能检出"和站名白边连成一片"的大药丸。

v1 的毛病：用白色连通域 + 填充率过滤 → 药丸一旦和站名文字的白描边连上，
连通域变成不规则大块，填充率 <0.55 被丢掉（黄木岗 60×57 填充 0.48 就是这样丢的）。

v2 做法：
 1) 白色掩膜的距离变换 dt（每点到最近非白的距离）
 2) 取 dt 的局部极大值（15×15 窗口内最大）且 dt>=8  → 白块的"圆心/中轴"
 3) 环形检验：在半径 r+3 处采样 32 个方向，>=70% 是非白 → 说明这块是"被包住的"，
    不是大块白色区域内部（大块白的内部环上仍是白，会被拒）
 4) 去重（15px 内合并）
 5) 必须贴到至少一条线色走廊（<=22px）→ 顺带剔掉图例噪声
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
COLOR.update({"4": "#E71615", "11": "#6D2041"})


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
dt = ndimage.distance_transform_edt(white)
mx = ndimage.maximum_filter(dt, size=15)
peak = (dt == mx) & (dt >= 8)
ys, xs = np.nonzero(peak)
print(f"局部极大值候选 {len(xs)} 个")

# 环形检验
ang = np.linspace(0, 2 * np.pi, 32, endpoint=False)
keep = []
H, W = dt.shape
for cy, cx in zip(ys, xs):
    r = dt[cy, cx]
    rr = r + 3.0
    ok = 0
    for a in ang:
        px = int(round(cx + rr * np.cos(a)))
        py = int(round(cy + rr * np.sin(a)))
        if not (0 <= px < W and 0 <= py < H) or not white[py, px]:
            ok += 1
    if ok / len(ang) >= 0.70:
        keep.append((int(cx), int(cy), float(r)))
print(f"通过环形检验 {len(keep)} 个")

# 去重
keep.sort(key=lambda t: -t[2])
pts = []
for cx, cy, r in keep:
    if all((cx - p[0]) ** 2 + (cy - p[1]) ** 2 > 225 for p in pts):
        pts.append((cx, cy, r))
print(f"去重后 {len(pts)} 个")

# 贴线过滤
DF = {}
for lid, c in COLOR.items():
    r0, g0, b0 = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r0) + np.abs(img[:, :, 1] - g0) + np.abs(img[:, :, 2] - b0)) <= 20
    DF[lid] = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))

xs0 = [s["x"] for s in ST.values()]; ys0 = [s["y"] for s in ST.values()]
BX = (min(xs0) - 250, max(xs0) + 250, min(ys0) - 250, max(ys0) + 250)
out = []
for cx, cy, r in pts:
    if not (BX[0] <= cx <= BX[1] and BX[2] <= cy <= BX[3]):
        continue
    touch = {}
    for lid, f in DF.items():
        d = float(f[cy, cx])
        if d <= 22:
            touch[lid] = round(d, 1)
    if touch:
        out.append({"cx": cx, "cy": cy, "r": round(r, 1), "touch": touch})
print(f"最终有效圆点 {len(out)} 个（v1 是 393 个）")
json.dump(out, open(SRC + "/logs/_markers_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 抽查：用户点名的几个站附近现在有没有圆点
for nm in ["深圳北", "布吉", "黄木岗", "赤湾", "福田口岸", "深圳湾公园", "后海", "湖贝", "红岭南", "嶂背", "坪山广场", "国展南"]:
    s = ST[nm]
    near = [o for o in out if abs(o["cx"] - s["x"]) <= 200 and abs(o["cy"] - s["y"]) <= 200]
    print(f"\n{nm} ({s['x']:.0f},{s['y']:.0f}) 附近 {len(near)} 个：")
    for o in sorted(near, key=lambda o: (o["cx"] - s["x"]) ** 2 + (o["cy"] - s["y"]) ** 2):
        print(f"    ({o['cx']},{o['cy']}) r={o['r']}  偏移({o['cx']-s['x']:+.0f},{o['cy']-s['y']:+.0f})  贴 {'/'.join(sorted(o['touch']))}")
