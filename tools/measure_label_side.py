# -*- coding: utf-8 -*-
"""只读/可写回：量原图里**每个站名摆在站点的哪个方位**，写进 stations.json 的
`official_label_side`（8 方向之一）。

用户原话：「文字根本就没有严格跟随站点，并且请把文字和地铁图中严格对照位置，
        文字到底是在站点圆圈的上下左右哪里对照好了」

原理（不用 OCR，认"文字是一块深色低饱和像素"就够了）：
  1. 以站点坐标为中心取 ±160px 窗口；
  2. 取**深色低饱和**像素（R/G/B 都 <110 且 max−min <45）—— 文字是黑的，
     而线路是饱和的彩色，天然被排除；
  3. 挖掉半径 34px 以内（那是站点圆点 / 药丸白心外那圈黑描边，不是站名）；
  4. 剩下的连通块里取**面积最大**的那块 = 站名文字块；
  5. 它的质心相对站点的方位 ⇒ right / left / top / bottom / rt / lt / rb / lb。

用法:
    python tools/measure_label_side.py            # 只报统计
    python tools/measure_label_side.py --apply    # 回写 stations.json
"""
import sys
import json
import math
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                   # noqa: E402
from PIL import Image                                # noqa: E402
from scipy import ndimage                            # noqa: E402

WIN = 160
INNER = 34          # 挖掉圆点/药丸黑边
MIN_AREA = 260      # 小于这个不算文字块
DARK = 110
DESAT = 45


def side_of(dx: float, dy: float) -> str:
    """图像/场景坐标都是 y 向下为正。"""
    ax, ay = abs(dx), abs(dy)
    if ax > ay * 2.0:
        return "right" if dx > 0 else "left"
    if ay > ax * 2.0:
        return "bottom" if dy > 0 else "top"
    if dx > 0:
        return "rb" if dy > 0 else "rt"
    return "lb" if dy > 0 else "lt"


def main():
    apply_ = "--apply" in sys.argv
    st_path = ROOT / "data" / "stations.json"
    data = json.load(open(st_path, encoding="utf-8"))
    st = data["stations"]
    arr = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB"))
    H, W, _ = arr.shape

    # ★★ v2.6.30：优先用 **OCR** 读出来的站名位置（data/ocr_labels.json）。
    #   像素法（认"最近的深色块"）会连到隔壁站名/线路黑边 ⇒ 量出来的方位有相当
    #   一部分是错的；而用户要的是"绝对照抄"，错一个就叠一个。
    #   OCR 有 1094 条（含标题等无关文本），按 text == 站名 精确配对，
    #   同名多条时取离站点最近的那个。
    ocr_path = ROOT / "data" / "ocr_labels.json"
    by_text = {}
    if ocr_path.exists():
        for e in json.load(open(ocr_path, encoding="utf-8")):
            # ★★★ v2.6.30b：ocr 给的 x,y 是**左上角**，不是中心。
            #   拿左上角算方位会整体往「左 / 上」偏一个半字身 —— 实测世界之窗
            #   rb→right、会展中心 top→rt、科学馆 left→bottom，就是这么错的。
            e = dict(e)
            e["cx"] = float(e.get("x", 0)) + float(e.get("w", 0)) * 0.5
            e["cy"] = float(e.get("y", 0)) + float(e.get("h", 0)) * 0.5
            by_text.setdefault(str(e.get("text") or ""), []).append(e)
    n_ocr = 0

    got, miss = {}, []
    for name, s in st.items():
        x, y = float(s.get("x", 0)), float(s.get("y", 0))
        cands_ocr = by_text.get(name) or []
        if cands_ocr:
            best = min(cands_ocr,
                       key=lambda e: math.hypot(e["cx"] - x, e["cy"] - y))
            dd = math.hypot(best["cx"] - x, best["cy"] - y)
            if dd <= 260.0:                      # 太远 = 配错了（同名出现在别处）
                got[name] = side_of(best["cx"] - x, best["cy"] - y)
                n_ocr += 1
                continue
        x0, y0 = max(0, int(x) - WIN), max(0, int(y) - WIN)
        x1, y1 = min(W, int(x) + WIN), min(H, int(y) + WIN)
        if x1 - x0 < 20 or y1 - y0 < 20:
            miss.append(name)
            continue
        sub = arr[y0:y1, x0:x1].astype(np.int16)
        mx = sub.max(axis=2)
        mn = sub.min(axis=2)
        dark = (mx < DARK) & ((mx - mn) < DESAT)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dist = np.hypot(xx - x, yy - y)
        mask = dark & (dist >= INNER)
        if mask.sum() < MIN_AREA:
            miss.append(name)
            continue
        lab, n = ndimage.label(mask)
        if n <= 0:
            miss.append(name)
            continue
        # ★ 取**离站点最近**的那块，不是最大的那块：
        #   取最大会连到隔壁站的站名/图例/框线，实测方位清一色变成 lt/top/left
        #   （188/121/59，一个 right/bottom 都没有 —— 一看就是取错了）。
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        cands = []
        for i in range(1, n + 1):
            if sizes[i - 1] < MIN_AREA:
                continue
            ys, xs = np.nonzero(lab == i)
            h = ys.max() - ys.min() + 1
            w = xs.max() - xs.min() + 1
            # 站名是"一行字"：高 20~80、宽 ≥ 高（多数字），且不能是一大团
            if not (18 <= h <= 90 and w >= 20 and max(w, h) / min(w, h) <= 6.0):
                continue
            ccx, ccy = xs.mean() + x0 - x, ys.mean() + y0 - y
            cands.append((math.hypot(ccx, ccy), ccx, ccy))
        if not cands:
            miss.append(name)
            continue
        cands.sort()
        _d, cx, cy = cands[0]
        got[name] = side_of(cx, cy)

    from collections import Counter
    c = Counter(got.values())
    print("量到 %d 站（其中 OCR 命中 %d，像素法兜底 %d），量不到 %d 站"
          % (len(got), n_ocr, len(got) - n_ocr, len(miss)))
    print("方位分布：" + ", ".join("%s=%d" % (k, v) for k, v in c.most_common()))
    if miss:
        print("量不到的（前 12）：" + ", ".join(miss[:12]))

    if apply_:
        bak = st_path.with_suffix(".json.bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy(st_path, bak)
        n = 0
        for name, side in got.items():
            if name in st:
                st[name]["official_label_side"] = side
                n += 1
        data["stations"] = st
        json.dump(data, open(st_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("[APPLY] 写入 %d 站的 official_label_side（备份 %s）" % (n, bak.name))


if __name__ == "__main__":
    main()
