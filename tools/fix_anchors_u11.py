# -*- coding: utf-8 -*-
"""u11 锚位修复：四段走廊两端的站点锚位偏出官方中心线 8~10px（_diag_u11 实测）。

量法＝文锦同款「带色断档法」：沿走廊的**垂线**扫描官方图，
带色中断的那一截就是站洞，洞心即真锚位（洞宽 23~26 为真站洞）。
  · 单线站（下梅林/梅村/高新南/深湾/晒布）→ 直接修 stations.json 的 x/y；
  · 换乘站（老街 1/3、红树湾南 9/11）→ 只修 lanes[本线] 的 dx/dy，
    绝不动主坐标（另一条线的锚位是好的）。

只改沿垂线的分量（洞心在扫描线上的位置），不动沿走廊的分量。
★ 已关 exe；改的是 源码/data，改完同步回 软件/data。
"""
import json
import math
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ST_FILE = DATA / "stations.json"
LN_FILE = DATA / "lines.json"
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB"), dtype=np.int16)

COLORS = {
    "3": (0, 160, 208),
    "9": (128, 96, 112),
}
TOL = 48

# (站名, 线号, 是否单线站[True=动x/y, False=动lanes])
FIXES = [
    ("下梅林", "9", True),
    ("梅村", "9", True),
    ("高新南", "9", True),
    ("深湾", "9", True),
    ("晒布", "3", True),
    ("老街", "3", False),
    ("红树湾南", "9", False),
]

ST = json.loads(ST_FILE.read_text(encoding="utf-8"))
LN = json.loads(LN_FILE.read_text(encoding="utf-8"))
SMS = ST["stations"] if isinstance(ST["stations"], dict) else {
    s["station_name"]: s for s in ST["stations"]}
LINES = {L["id"]: L for L in LN["lines"]}


def corridor_xy(name, lid):
    s = SMS[name]
    d = (s.get("lanes") or {}).get(str(lid))
    x, y = float(s["x"]), float(s["y"])
    if d:
        return x + float(d[0]), y + float(d[1])
    return x, y


def corridor_dir(name, lid):
    """走廊方向：优先 lanes 角度，否则用两侧邻站锚位连线。返回单位向量。"""
    s = SMS[name]
    d = (s.get("lanes") or {}).get(str(lid))
    if d and len(d) >= 3 and float(d[3]) >= 3.0:
        a = math.radians(float(d[2]))
        return math.cos(a), math.sin(a)
    seq = [n for n in (LINES[lid].get("stations") or []) if n in SMS]
    i = seq.index(name)
    pts = []
    for j in (i - 1, i + 1):
        if 0 <= j < len(seq):
            q = corridor_xy(seq[j], lid)
            p = corridor_xy(name, lid)
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            if L > 1:
                pts.append(((q[0] - p[0]) / L, (q[1] - p[1]) / L))
    if not pts:
        return None
    dx = sum(p[0] for p in pts)
    dy = sum(p[1] for p in pts)
    L = math.hypot(dx, dy)
    if L < 1e-6:      # 两侧反向抵消（拐点站）⇒ 退回单侧
        return pts[0]
    return dx / L, dy / L


def hole_center(px, py, ux, uy, half=45.0, step=0.5):
    """沿 (ux,uy) 方向过 (px,py) 扫描，找带色断档（站洞）中心。
    返回 (洞心t, 洞宽) 或 None。"""
    c = np.array(COLORS[lid_for_scan], dtype=np.int16)
    ts = np.arange(-half, half + 1e-9, step)
    on = []
    for t in ts:
        x = int(round(px + ux * t))
        y = int(round(py + uy * t))
        if not (0 <= x < OFF.shape[1] and 0 <= y < OFF.shape[0]):
            on.append(False)
            continue
        on.append(bool(np.abs(OFF[y, x] - c).sum() < TOL))
    # 找最长 False 游程（站洞）
    best = None          # (长度, 起点 idx)
    i = 0
    n = len(on)
    while i < n:
        if not on[i]:
            j = i
            while j < n and not on[j]:
                j += 1
            if best is None or (j - i) > best[0]:
                best = (j - i, i)
            i = j
        else:
            i += 1
    if best is None:
        return None
    L, i0 = best
    w = L * step
    if not (18.0 <= w <= 70.0):      # 太窄=噪声，太宽=出带子
        return None
    t_mid = float(ts[i0] + ts[i0 + L - 1]) / 2.0
    return t_mid, w


lid_for_scan = "9"


def main():
    apply_ = "--apply" in sys.argv
    rows = []
    for name, lid, single in FIXES:
        s = SMS[name]
        ax, ay = corridor_xy(name, lid)
        d = corridor_dir(name, lid)
        if d is None:
            print("[跳] %s(%s)：走廊方向不明" % (name, lid))
            continue
        dx, dy = d
        px, py = -dy, dx                      # 垂线
        lid_for_scan = lid
        r = hole_center(ax, ay, px, py)
        if r is None:
            print("[跳] %s(%s)：垂线上找不到可信站洞" % (name, lid))
            continue
        t_mid, w = r
        ex, ey = px * t_mid, py * t_mid       # 锚位修正向量
        dev = math.hypot(ex, ey)
        rows.append((name, lid, single, ex, ey, dev, w))
        print("[量] %-5s(%s) 洞宽=%.1f 偏移=(%+.1f,%+.1f) |%.1f|px  %s" % (
            name, lid, w, ex, ey, dev,
            "单线→动x/y" if single else "换乘→动lanes"))
    if not apply_:
        print("（预演，--apply 生效）")
        return 0
    bak_st = DATA / ("stations.json.bak_anc11_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(ST_FILE, bak_st)
    print("[备份] %s" % bak_st.name)
    for name, lid, single, ex, ey, dev, w in rows:
        s = SMS[name]
        if single:
            s["x"] = round(float(s["x"]) + ex, 1)
            s["y"] = round(float(s["y"]) + ey, 1)
            print("[改] %-5s x/y → (%s, %s)" % (name, s["x"], s["y"]))
        else:
            lanes = s.setdefault("lanes", {})
            d = lanes.get(lid)
            if d is None:
                print("[跳] %-5s lanes[%s] 不存在，不敢新建" % (name, lid))
                continue
            d[0] = round(float(d[0]) + ex, 1)
            d[1] = round(float(d[1]) + ey, 1)
            print("[改] %-5s lanes[%s] → (%s, %s)" % (name, lid, d[0], d[1]))
    tmp = ST_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ST, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ST_FILE)
    print("[写入] %s" % ST_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
