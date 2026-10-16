"""从原图反推每条线路的真实站序 —— 审计的权威依据。

原理：
  1. 每个站点标记 -> 采样它周围一圈的颜色 -> 得出"这个标记属于哪些线路"
  2. 每个 OCR 站名 -> 找最近的标记 -> 得出"这个标记叫什么名字"
  3. 对每条线路：取出所有"环色含本线颜色"的标记，用最近邻链排序
  4. 打印站序，与 data/lines.json 对比即可发现漏站 / 错站 / 错序

用法:
  python tools/derive_line_sequences.py            # 全部线路
  python tools/derive_line_sequences.py 9 4 13     # 只看指定线路
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

LEGEND = {
    "1": (0x00, 0xB0, 0x52), "2": (0xBA, 0x57, 0x00), "3": (0x00, 0xA6, 0xDE),
    "4": (0xD4, 0x2E, 0x12), "5": (0x9E, 0x4D, 0xAB), "6": (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7": (0x00, 0x33, 0xAB), "8": (0xBA, 0x57, 0x00),
    "9": (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
    "有轨电车": (0xB6, 0xB6, 0xB7), "有轨电车支线": (0xB6, 0xB6, 0xB7),
    "坪山云巴": (0xB6, 0xB6, 0xB7),
}
# 原图里同色的线路
ALIAS = {"2": "2|8", "8": "2|8",
         "有轨电车": "TRAM", "有轨电车支线": "TRAM", "坪山云巴": "YUNBA"}
# 灰色标记的区分：靠地理位置
YUNBA_BOX = (6600, 2500, 7500, 3500)
TRAM_BOX = (2950, 2200, 4000, 3100)

COLOR_TOL = 26
RING_HIT = 0.12
NAME_R = 300.0

# 印在图上但不是站名的文字
STOPWORDS = {
    "图例", "深圳地铁", "深圳", "东莞", "惠州", "香港", "大鹏湾", "深圳湾", "深汕特别合作区",
    "深圳市轨道交通运营线路", "运营线路", "线路图", "有轨电车线路图", "坪山云巴线路图",
    "换乘站", "普通站", "出闸换乘", "机场", "高铁", "长途汽车站", "公交", "有轨电车", "云巴",
    "市民中心", "会展中心", "您的位置", "非付费区", "付费区",
}


def ring_colors(img, x, y, mw, mh):
    r_in = max(mw, mh) / 2.0 + 2.0
    r_out = r_in + 16.0
    xi, yi = int(round(x)), int(round(y))
    y0, y1 = max(0, int(yi - r_out)), min(img.shape[0], int(yi + r_out) + 1)
    x0, x1 = max(0, int(xi - r_out)), min(img.shape[1], int(xi + r_out) + 1)
    patch = img[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - yi) ** 2 + (xx - xi) ** 2
    sel = patch[(d2 >= r_in ** 2) & (d2 <= r_out ** 2)]
    if len(sel) < 40:
        return set()
    out = set()
    for lid, c in LEGEND.items():
        dd = np.abs(sel - np.array(c, dtype=np.int16)).max(axis=1)
        if float((dd <= COLOR_TOL).mean()) > RING_HIT:
            out.add(ALIAS.get(lid, lid))
    # 灰色再按位置细分成 TRAM / YUNBA
    if "TRAM" in out or "YUNBA" in out:
        out.discard("TRAM")
        out.discard("YUNBA")
        if TRAM_BOX[0] <= x <= TRAM_BOX[2] and TRAM_BOX[1] <= y <= TRAM_BOX[3]:
            out.add("TRAM")
        if YUNBA_BOX[0] <= x <= YUNBA_BOX[2] and YUNBA_BOX[1] <= y <= YUNBA_BOX[3]:
            out.add("YUNBA")
    return out


def box_dist(lb, mx, my):
    x0, y0 = lb["x"], lb["y"]
    x1, y1 = lb["x"] + lb["w"], lb["y"] + lb["h"]
    dx = max(x0 - mx, 0.0, mx - x1)
    dy = max(y0 - my, 0.0, my - y1)
    return (dx * dx + dy * dy) ** 0.5


def chain_order(pts):
    """最近邻链排序（pts: [(x,y,name)]），返回排序后的列表。"""
    if len(pts) <= 2:
        return pts
    a = np.array([p[:2] for p in pts], dtype=float)
    # 从最"边角"的点起（离质心最远）
    c = a.mean(axis=0)
    i0 = int(np.argmax(((a - c) ** 2).sum(axis=1)))
    used = [i0]
    left = set(range(len(pts))) - {i0}
    while left:
        last = a[used[-1]]
        j = min(left, key=lambda k: ((a[k] - last) ** 2).sum())
        used.append(j)
        left.discard(j)
    return [pts[i] for i in used]


def main():
    want = set(sys.argv[1:])
    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    markers = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    labels = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))
    img = np.asarray(Image.open(IMG).convert("RGB")).astype(np.int16)

    # ---- 标记 -> 线路集合 ----
    mk = []
    for m in markers:
        w, h = float(m["w"]), float(m["h"])
        if min(w, h) < 16 or max(w, h) > 130:
            continue
        rc = ring_colors(img, m["x"], m["y"], w, h)
        if not rc:
            continue
        mk.append({"x": m["x"], "y": m["y"], "w": w, "h": h, "lines": rc, "name": None})
    print(f"有效标记 {len(mk)}")

    # ---- 标记 -> 名字（全局贪心：距离最近的先配） ----
    cand = []
    for lb in labels:
        t = lb["text"].replace(" ", "")
        if not (2 <= len(t) <= 7):
            continue
        if any(not ("\u4e00" <= ch <= "\u9fff") for ch in t):
            continue
        if t in STOPWORDS:
            continue
        cand.append(lb)
    print(f"中文候选标签 {len(cand)}")

    PAIRS_MAX = 900
    pairs = []
    for li, lb in enumerate(cand):
        for mi, m in enumerate(mk):
            d = box_dist(lb, m["x"], m["y"])
            if d <= NAME_R:
                pairs.append((d, li, mi))
    pairs.sort()
    used_l, used_m = set(), set()
    for d, li, mi in pairs:
        if li in used_l or mi in used_m:
            continue
        used_l.add(li)
        used_m.add(mi)
        mk[mi]["name"] = cand[li]["text"].replace(" ", "")
    print(f"命名成功 {sum(1 for m in mk if m['name'])} / {len(mk)}")
    _ = PAIRS_MAX

    # ---- 逐线输出 ----
    lines = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
    out = {}
    for L in lines:
        lid = L["id"]
        key = ALIAS.get(lid, lid)
        sub = [m for m in mk if key in m["lines"] and m["name"]]
        pts = [(m["x"], m["y"], m["name"]) for m in sub]
        seq = chain_order(pts)
        names = [p[2] for p in seq]
        out[lid] = {"chain": [{"name": p[2], "x": p[0], "y": p[1]} for p in seq]}
        if want and lid not in want:
            continue
        have = set(L["stations"])
        extra = [n for n in names if n not in have]
        lost = [n for n in L["stations"] if n not in names]
        print("=" * 72)
        print(f"[{lid}] {L.get('name')}  图上读到 {len(names)} 站，我的表 {len(have)} 站")
        print("  图序: " + " → ".join(names))
        if extra:
            print(f"  ★ 图上有、我表里没有 ({len(extra)}): " + "、".join(extra))
        if lost:
            print(f"  ☆ 我表里有、图上没读到 ({len(lost)}): " + "、".join(lost))
    (DATA / "derived_chains.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[OK] 图序已导出 -> {DATA / 'derived_chains.json'}")
    _ = stations


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
