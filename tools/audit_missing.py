"""审计：找出贴着某条线路走廊、但不在该线路站表里的站点（遗漏候选）。

原理：
  1. 按线路色抠走廊掩膜 -> 距离场
  2. OCR 站名标签中心到走廊的最近距离
  3. 距离 < TOL 且不在该线站表 -> 报为「遗漏候选」
  4. 反向：在站表里但离走廊很远 -> 报为「可疑站」
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

TOL = 150.0        # 站名标签中心到走廊的容忍距离（px）
TOL_FAR = 420.0    # 站表里的站离走廊超过这个距离 -> 可疑
TOLOR = 20         # 线路色容差


def load():
    lines = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    labels = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))
    return lines, stations, labels


def corridor_dist(im, hexcolor, tol=TOLOR, dilate=0):
    t = np.array([int(hexcolor[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.int16)
    d = np.abs(im - t).max(axis=2)
    m = d <= tol
    if dilate:
        m = ndimage.binary_dilation(m, iterations=dilate)
    if not m.any():
        return None
    return ndimage.distance_transform_edt(~m)


def main():
    lines, stations, labels = load()
    print("载入原图 ...")
    im = np.array(Image.open(IMG).convert("RGB")).astype(np.int16)

    # 站名候选：2~6 个汉字的标签
    cand = []
    for lb in labels:
        t = lb["text"]
        if not (2 <= len(t) <= 6):
            continue
        if any(not ("\u4e00" <= ch <= "\u9fff") for ch in t):
            continue
        cand.append((t, lb["x"] + lb["w"] / 2.0, lb["y"] + lb["h"] / 2.0, lb.get("score", 0)))

    for L in lines:
        dd = corridor_dist(im, L["color"])
        if dd is None:
            print(f"!! {L['id']} {L['color']} 找不到走廊")
            continue
        in_line = set(L["stations"])

        # 1) 遗漏候选
        near = []
        for t, cx, cy, sc in cand:
            if t in in_line:
                continue
            # 该站如果属于别的线，且被别的线走廊覆盖得更近，则不算本线遗漏
            dv = float(dd[int(cy), int(cx)])
            if dv < TOL:
                near.append((dv, t, cx, cy))
        near.sort()

        # 2) 可疑站（在站表里但离走廊远）
        far = []
        for sid in L["stations"]:
            st = stations.get(sid)
            if not st:
                far.append((9e9, sid, None))
                continue
            dv = dd[int(st["y"]), int(st["x"])]
            if dv > TOL_FAR:
                far.append((dv, sid, (st["x"], st["y"])))
        far.sort(reverse=True)

        print("=" * 70)
        print(f"[{L['id']}] {L.get('name')} {L['color']}  站表 {len(L['stations'])} 站")
        if near:
            print(f"  -- 遗漏候选（走廊 {TOL}px 内、不在站表）:")
            for dv, t, cx, cy in near[:40]:
                print(f"     {t:<8s} 距走廊 {dv:6.1f}px  @({cx:.0f},{cy:.0f})")
        else:
            print("  -- 遗漏候选: 无")
        if far:
            print(f"  -- 可疑站（离走廊 >{TOL_FAR}px）:")
            for dv, sid, xy in far[:15]:
                s = f"@{xy[0]:.0f},{xy[1]:.0f}" if xy else "【站表里没有这个站】"
                print(f"     {sid:<8s} {dv:8.1f}px  {s}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
