# -*- coding: utf-8 -*-
"""只读：读原图下方的两张独立示意小图（有轨电车线路图 / 坪山云巴线路图）。
圆点按 x 排序 → 与 OCR 站名文字就近匹配 → 输出真值坐标。
产物 logs/_mini_maps.json（不写业务数据）。
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
OCR = json.load(open(SRC + "/data/ocr_labels.json", encoding="utf-8"))


def dots(x0, y0, x1, y1, amin=150):
    sub = img[y0:y1, x0:x1]
    w = (np.abs(sub[:, :, 0] - 254) + np.abs(sub[:, :, 1] - 254) + np.abs(sub[:, :, 2] - 254)) <= 10
    w = ndimage.binary_erosion(w, np.ones((3, 3)))
    lab, n = ndimage.label(w, np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) < amin:
            continue
        if max(int(xs.max()-xs.min()+1), int(ys.max()-ys.min()+1)) > 90:
            continue   # 横线/标题等大块白斑不是站点
        out.append((int(xs.mean()) + x0, int(ys.mean()) + y0,
                    int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
    return sorted(out)


def texts(x0, y0, x1, y1):
    """只留纯中文站名（2~6 字），去掉英文与长句"""
    r = []
    for o in OCR:
        t = str(o.get("text", ""))
        if not (2 <= len(t) <= 6):
            continue
        if not all("\u4e00" <= c <= "\u9fff" for c in t):
            continue
        if x0 <= o["x"] <= x1 and y0 <= o["y"] <= y1:
            r.append((o["x"], o["y"], t))
    return sorted(r)


def match(pts, txs, dy_max=70):
    """圆点 x 排序 ↔ 文字 x 排序，按 x 就近一对一（文字通常在圆点正上/下方）"""
    used, res = set(), []
    for px, py, pw, ph in pts:
        best = None
        for i, (tx, ty, t) in enumerate(txs):
            if i in used:
                continue
            d = abs(tx - px)   # 小图是横排，文字都在同一带，只看 x 距离更稳
            if abs(tx - px) > 130:
                continue
            if best is None or d < best[0]:
                best = (d, i)
        if best:
            used.add(best[1])
            res.append((txs[best[1]][2], px, py, pw, ph))   # 注意：别用泄漏的循环变量 t
        else:
            res.append(("?", px, py, pw, ph))
    return res


MAPS = {
    "有轨电车主线": (5800, 6250, 7750, 6400, 2243 - 2243 + 6150, 6345),   # 圆点 y≈6328
    "有轨电车支线": (6450, 6450, 7750, 6560, 0, 0),
    "坪山云巴": (5800, 6820, 7750, 6950, 0, 0),
}
REGION = {
    "有轨电车主线": (5800, 6270, 7750, 6390),
    "有轨电车支线": (6450, 6430, 7750, 6560),
    "坪山云巴": (5800, 6840, 7750, 6930),
}
TXBOX = {
    "有轨电车主线": (5750, 6220, 7750, 6300),
    "有轨电车支线": (6700, 6490, 7750, 6560),
    "坪山云巴": (5800, 6760, 7750, 6830),
}

out = {}
for name, (rx0, ry0, rx1, ry1) in REGION.items():
    tx0, ty0, tx1, ty1 = TXBOX[name]
    pts = dots(rx0, ry0, rx1, ry1)
    txs = texts(tx0, ty0, tx1, ty1)
    m = match(pts, txs)
    out[name] = [{"name": t, "x": px, "y": py, "w": pw, "h": ph} for t, px, py, pw, ph in m]
    print("== %s：圆点 %d 个，文字 %d 条 ==" % (name, len(pts), len(txs)))
    for t, px, py, pw, ph in m:
        print("   %-8s (%4d,%4d) %2dx%-2d%s" % (t, px, py, pw, ph, "  ←药丸(换乘)" if max(pw, ph) >= 30 else ""))

json.dump(out, open(SRC + "/logs/_mini_maps.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n已存 logs/_mini_maps.json")
