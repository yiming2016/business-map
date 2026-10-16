# -*- coding: utf-8 -*-
"""只读：查「同名两个站体」的站（清湖/湖贝/红岭南/坪山中心）周围有哪些白圆点、
每个圆点贴哪条线的颜色、附近有什么站名文字。用来确定第二个站体该画在哪。
用法：python tools/_probe_twin_stations.py
"""
import json
import math
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]
OCR = json.load(open(SRC + "/data/ocr_labels.json", encoding="utf-8"))
LJ = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = LJ["lines"] if isinstance(LJ, dict) and "lines" in LJ else LJ
COLOR = {str(l["id"]): l["color"] for l in _l}
COLOR.update({"4": "#E71615", "11": "#6D2041"})


def hx(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)])


REFS = {lid: hx(c) for lid, c in COLOR.items()}


def line_colors(x, y, R=30):
    x, y = int(x), int(y)
    sub = img[y - R:y + R, x - R:x + R].reshape(-1, 3)
    return {lid: int((np.abs(sub - r).sum(axis=1) <= 20).sum())
            for lid, r in REFS.items()}


def dots(x0, y0, x1, y1):
    sub = img[y0:y1, x0:x1]
    w = (np.abs(sub[:, :, 0] - 254) + np.abs(sub[:, :, 1] - 254) + np.abs(sub[:, :, 2] - 254)) <= 10
    w = ndimage.binary_erosion(w, np.ones((3, 3)))
    lab, n = ndimage.label(w, np.ones((3, 3)))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        ww = sl[1].stop - sl[1].start
        if h < 8 or ww < 8:
            continue
        if min(h, ww) > 60:          # 大块白斑（文字区）不算站
            continue
        out.append((int((sl[1].start + sl[1].stop) / 2) + x0,
                    int((sl[0].start + sl[0].stop) / 2) + y0, ww, h))
    return sorted(out)


TARGET = ["清湖", "湖贝", "红岭南", "坪山中心"]
RAD = 260
for nm in TARGET:
    s = ST[nm]
    x, y = float(s["x"]), float(s["y"])
    print("=" * 70)
    print("%s  lines=%s  当前主站体 (%d,%d)" % (nm, s["lines"], x, y))
    x0, y0 = max(0, int(x) - RAD), max(0, int(y) - RAD)
    x1, y1 = int(x) + RAD, int(y) + RAD
    for px, py, pw, ph in dots(x0, y0, x1, y1):
        d = math.hypot(px - x, py - y)
        cols = line_colors(px, py)
        top = sorted(cols.items(), key=lambda kv: -kv[1])[:3]
        top = ["%s×%d" % (k, v) for k, v in top if v >= 40]
        who = [k for k, v in ST.items() if abs(v["x"] - px) < 12 and abs(v["y"] - py) < 12]
        print("   (%4d,%4d) %2dx%-2d 距主站%5.0f  %s  %s%s"
              % (px, py, pw, ph, d, " ".join(top) or "无色",
                 "←" + who[0] if who else "", "  [药丸]" if max(pw, ph) >= 30 else ""))
    tx = [o for o in OCR if x0 <= o["x"] <= x1 and y0 <= o["y"] <= y1
          and all("\u4e00" <= c <= "\u9fff" for c in str(o.get("text", "")))
          and 2 <= len(str(o.get("text", ""))) <= 6]
    print("   附近中文文字: " + ", ".join("%s(%d,%d)" % (o["text"], o["x"], o["y"]) for o in tx[:10]))
