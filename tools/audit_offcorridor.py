"""走廊体检（v2.4）：

1. 每条线按实测色抠出走廊（不加膨胀，避免串线），算每个站到本条线走廊的距离。
   距离过大的站 = 坐标错位 / 站线归属错误。
2. 标记(markers.json) 里落在某条线走廊上、但附近没有任何已收录站的 ->
   疑似"漏掉的站"，并给出最近的 OCR 站名。

用法:
  python tools/audit_offcorridor.py             # 全部
  python tools/audit_offcorridor.py 12 9        # 指定线路
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

DS = 2
TOL = 12            # 颜色容差（每通道最大值）
OFF_MAX = 30.0      # 站到走廊允许距离（原图 px）
HIT_R = 26.0        # 标记命中走廊的半径（原图 px）
DUP_R = 60.0        # 标记与已收录站的最小间距（原图 px）

# 实测自原图的线路色（低饱和线也包含）
LINE_RGB = {
    "1": (0, 174, 78), "2": (186, 84, 0), "3": (0, 162, 222), "4": (228, 18, 18),
    "5": (156, 72, 168), "6": (0, 192, 180), "6支": (0, 138, 126), "7": (0, 48, 168),
    "8": (186, 84, 0), "9": (138, 102, 108), "10": (246, 114, 144), "11": (108, 30, 60),
    "12": (168, 144, 174), "13": (210, 132, 0), "14": (234, 204, 96), "16": (60, 18, 162),
    "20": (150, 216, 222), "有轨电车": (180, 180, 180),
    "有轨电车支线": (180, 180, 180), "坪山云巴": (180, 180, 180),
}


def masks_for(img, rgb):
    c = np.array(rgb, np.int16)
    d = np.zeros(img.shape[:2], np.int16)
    for k in range(3):
        d = np.maximum(d, np.abs(img[:, :, k].astype(np.int16) - c[k]))
    return d <= TOL


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    im = Image.open(IMG).convert("RGB")
    img = np.asarray(im.resize((im.width // DS, im.height // DS), Image.NEAREST))
    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    ln = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))["lines"]
    mk = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    lb = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))

    cache = {}
    for entry in ln:
        lid = entry["id"]
        if want and lid not in want:
            continue
        rgb = LINE_RGB.get(lid)
        if rgb is None:
            print(f"[{lid}] 无实测色，跳过")
            continue
        if rgb not in cache:
            m = masks_for(img, rgb)
            dt = ndimage.distance_transform_edt(~m) * DS
            cache[rgb] = (m, dt)
        m, dt = cache[rgb]
        tot = int(m.sum())
        seq = [n for n in entry["stations"] if n in st]
        print(f"\n===== {lid:<6s} 走廊像素(2x) {tot:>7d}  站数 {len(seq)}")
        if tot < 200:
            print("   !! 走廊几乎为空，色值可能不对")
            continue

        off = []
        on_pos = []
        for n in seq:
            x, y = st[n]["x"] / DS, st[n]["y"] / DS
            iy, ix = int(round(y)), int(round(x))
            d = float(dt[max(0, iy - 1):iy + 2, max(0, ix - 1):ix + 2].min())
            on_pos.append((st[n]["x"], st[n]["y"], n))
            if d > OFF_MAX:
                off.append((n, round(d)))
        if off:
            print("   ★ 不在本条线走廊上的站: " +
                  "、".join(f"{n}({d}px)" for n, d in sorted(off, key=lambda z: -z[1])))
        else:
            print("   OK 全部站都在走廊上")

        # 走廊上未被收录的标记
        miss = []
        for mm in mk:
            mx, my = mm["x"] / DS, mm["y"] / DS
            iy, ix = int(round(my)), int(round(mx))
            if not (0 <= iy < dt.shape[0] and 0 <= ix < dt.shape[1]):
                continue
            if dt[iy, ix] > HIT_R:
                continue
            if min(math.dist((mm["x"], mm["y"]), p[:2]) for p in on_pos) <= DUP_R:
                continue
            # 找最近 OCR 名
            best = None
            for b in lb:
                t = b["text"].replace(" ", "")
                if not (2 <= len(t) <= 7):
                    continue
                d2 = math.dist((b["x"] + b["w"] / 2, b["y"] + b["h"] / 2), (mm["x"], mm["y"]))
                if d2 < 320 and (best is None or d2 < best[1]):
                    best = (t, d2)
            miss.append((mm["x"], mm["y"], mm.get("w"), mm.get("h"),
                         best[0] if best else "?", round(best[1]) if best else -1))
        if miss:
            print(f"   ☆ 走廊上疑似漏收录的标记 {len(miss)} 个:")
            for x, y, w, h, t, d2 in sorted(miss, key=lambda z: z[1]):
                print(f"        ({x:>7.1f},{y:>7.1f}) {w}x{h}  最近名≈{t} ({d2}px)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
