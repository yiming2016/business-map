# -*- coding: utf-8 -*-
"""门3 第5轮：修 2 个「当前坐标完全不贴本站所属线」的站。
判据：当前位置 R=30 内测不到本站任何一条线的颜色；新位置测到 ×800 以上。
改完立刻验证：①新位置必须贴本站某条线 ②相邻站距离不得异常。写前自动备份。
"""
import json
import shutil
import time
import numpy as np
from PIL import Image

SRC = "C:/software/subway/源码"
TS = time.strftime("%Y%m%d_%H%M%S")
SP = SRC + "/data/stations.json"
LP = SRC + "/data/lines.json"
for p in (SP, LP):
    shutil.copy(p, "%s.bak_stage8_%s" % (p, TS))

img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
S = json.load(open(SP, encoding="utf-8"))
L = json.load(open(LP, encoding="utf-8"))
ST = S["stations"]
LINES = L["lines"]
_l = L["lines"] if isinstance(L, dict) and "lines" in L else L
COLOR = {str(l["id"]): l["color"] for l in _l}
COLOR.update({"4": "#E71615", "11": "#6D2041"})


def hx(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)])


REFS = {lid: hx(c) for lid, c in COLOR.items()}


def hits(x, y, lids, R=30):
    """该点周围 R 内，属于本站各线的像素数"""
    x, y = int(x), int(y)
    sub = img[y - R:y + R, x - R:x + R].reshape(-1, 3)
    out = {}
    for lid in lids:
        r = REFS.get(lid)
        if r is None:
            continue
        out[lid] = int((np.abs(sub - r).sum(axis=1) <= 20).sum())
    return out


def seq(lid):
    for l in LINES:
        if str(l["id"]) == lid:
            return l["stations"]
    raise KeyError(lid)


FIX = {
    "大剧院": (4767, 5035),     # 当前(4613,5077) 完全不贴 1/2/5；新点 5号线×819
    "黄贝岭": (5016, 5035),     # 当前(5141,5078) 完全不贴 2/5；  新点 5号线×805
}

for nm, (nx, ny) in FIX.items():
    s = ST[nm]
    old = (s["x"], s["y"])
    before = hits(old[0], old[1], s["lines"])
    after = hits(nx, ny, s["lines"])
    print("%s  %s" % (nm, s["lines"]))
    print("   旧 (%d,%d) → %s" % (old[0], old[1], before))
    print("   新 (%d,%d) → %s" % (nx, ny, after))
    if not after or max(after.values()) < 200:
        print("   ✗ 新位置不贴任何所属线，跳过不改")
        continue
    s["x"], s["y"] = float(nx), float(ny)
    print("   ✓ 已改")

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入（备份 .bak_stage8_%s）" % TS)

# ---- 自检：相邻站距离（阈值放宽到 1200，宝安→前海湾 935px 是真实大跨）----
err = []
for l in LINES:
    s = l["stations"]
    for a, b in zip(s, s[1:]):
        if a not in ST or b not in ST:
            continue
        d = ((ST[a]["x"] - ST[b]["x"]) ** 2 + (ST[a]["y"] - ST[b]["y"]) ** 2) ** 0.5
        if d > 1200:
            err.append("%s号线 %s→%s 相距 %.0fpx" % (l["id"], a, b, d))
print("相邻站距检查：%s" % ("；".join(err) if err else "全部正常"))
