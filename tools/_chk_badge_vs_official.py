# -*- coding: utf-8 -*-
"""只读：核「线路号方块」的落点跟**原图**对不对。

做法：拿渲染出来的每个方块中心，回到原图那个位置附近，用跟
`measure_terminal_badges.py` **同一套**检测（DT≥15 种子 + 只在 DT≥7 的像素里连通
+ 尺寸 95~150 + 长宽比≥0.75）找方块：
  · 找得到 ⇒ 报偏差（中心距）；
  · 找不到 ⇒ 那个位置原图上没有方块（要么我们摆错了，要么原图本来就没画）。

用法:
    python tools/_chk_badge_vs_official.py [窗口半边长]
"""
import os
import sys
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                   # noqa: E402
from PIL import Image                                # noqa: E402
from scipy import ndimage                            # noqa: E402

from PySide6.QtWidgets import QApplication           # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841

from ui.map_view import build_terminal_badge_specs   # noqa: E402
from ui.metro_render import BADGE_SCENE, BADGE_GAP, BADGE_SPREAD  # noqa: E402

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
WIN = int(_args[0]) if _args else 90
DT_SEED, BODY_DT = 15.0, 7.0
SIZE_LO, SIZE_HI = 95.0, 150.0


def hex2rgb(h):
    h = (h or "").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def find_badge(arr, color, cx, cy, win=WIN):
    """在 (cx,cy) 附近找一块线路色的方块，返回 (中心x, 中心y, 尺寸) 或 None。"""
    H, W, _ = arr.shape
    x0, y0 = max(0, int(cx) - win), max(0, int(cy) - win)
    x1, y1 = min(W, int(cx) + win), min(H, int(cy) + win)
    sub = arr[y0:y1, x0:x1].astype(np.int16)
    d = np.abs(sub - np.array(color, dtype=np.int16)).sum(axis=2)
    mask = d < 48
    if mask.sum() < 200:
        return None
    dt = ndimage.distance_transform_edt(mask)
    if dt.max() < DT_SEED:
        return None
    seeds = dt >= DT_SEED
    lab, n = ndimage.label(seeds)
    best = None
    for i in range(1, n + 1):
        comp = lab == i
        body, _ = ndimage.label(dt >= BODY_DT)
        # 取该种子所在位置所属的那块 body
        ys, xs = np.nonzero(comp)
        if len(xs) == 0:
            continue
        b = body[ys[0], xs[0]]
        if b <= 0:
            continue
        m = body == b
        bys, bxs = np.nonzero(m)
        if len(bxs) < 400:
            continue
        w = bxs.max() - bxs.min() + 1
        h = bys.max() - bys.min() + 1
        if not (SIZE_LO <= w <= SIZE_HI and SIZE_HI >= h >= SIZE_LO):
            continue
        if min(w, h) / max(w, h) < 0.75:
            continue
        c_x = bxs.mean() + x0
        c_y = bys.mean() + y0
        dist = math.hypot(c_x - cx, c_y - cy)
        if best is None or dist < best[0]:
            best = (dist, c_x, c_y, w, h)
    return best


def main():
    st = json.load(open(ROOT / "data" / "stations.json", encoding="utf-8"))["stations"]
    ln = json.load(open(ROOT / "data" / "lines.json", encoding="utf-8"))
    lines = ln["lines"] if isinstance(ln, dict) and "lines" in ln else ln
    color_of = {str(L.get("id") or ""): hex2rgb(L.get("color")) for L in lines}
    meas = {}
    p = ROOT / "data" / "terminal_badges.json"
    if p.exists():
        meas = json.load(open(p, encoding="utf-8"))
    arr = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB"))

    specs = build_terminal_badge_specs(st, lines)
    print("方块总数 %d（原图量到 %d 条）" % (len(specs), len(meas)))
    print("terminal_badges.json 键示例：%s" % (sorted(meas)[:2],))
    rows = []
    for key, lid, x, y, ux, uy, dist, lane in specs:
        # 复现 TerminalBadgeItem._relayout 的摆位（场景坐标 == 原图像素）
        s = BADGE_SCENE
        gap = max(dist - s * 0.5, 0.0)
        off = lane * (s + BADGE_SPREAD)
        px, py = -uy, ux                       # lane 沿垂直方向错开
        cx = x + ux * (s * 0.5 + gap) + px * off
        cy = y + uy * (s * 0.5 + gap) + py * off
        got = find_badge(arr, color_of.get(str(lid), (0, 0, 0)), cx, cy)
        rows.append((key, lid, cx, cy, got))   # ★ key 是站名；terminal_badges.json 的键是 "线号|站名"

    hit = [r for r in rows if r[4]]
    miss = [r for r in rows if not r[4]]
    print("\n[原图上找得到方块的] %d 个：" % len(hit))
    ds = sorted(r[4][0] for r in hit)
    if ds:
        print("   中心偏差：min %.1f  中位 %.1f  平均 %.1f  max %.1f"
              % (ds[0], ds[len(ds) // 2], sum(ds) / len(ds), ds[-1]))
    for key, lid, cx, cy, got in sorted(hit, key=lambda r: -r[4][0])[:10]:
        print("   %-22s 线%-4s 我们(%6.0f,%6.0f) 原图(%6.0f,%6.0f) 偏差 %5.1f  尺寸 %dx%d"
              % (key, lid, cx, cy, got[1], got[2], got[0], got[3], got[4]))

    # ---- 可选：把「原图检测到的中心」回写进 terminal_badges.json ----
    # ★ 只回写**偏差 ≤20px** 的（确认是同一块方块）。牛湖那种 40px 的不动 ——
    #   它检出来的尺寸是 101x111（别处都是 112x112），很可能是检到了别的东西。
    if "--apply" in sys.argv:
        import shutil
        import time as _t
        bak = p.with_suffix(".json.bak_%s" % _t.strftime("%Y%m%d_%H%M%S"))
        shutil.copy(p, bak)
        fixed = 0
        for key, lid, x, y, ux, uy, dist, lane in specs:
            row = next((r for r in rows if r[0] == key and r[1] == lid), None)
            if not row or not row[4] or row[4][0] > 20.0:
                continue
            _dd0, c_x, c_y, _w, _h = row[4]
            mkey = "%s|%s" % (lid, key)
            _s = BADGE_SCENE
            off = lane * (_s + BADGE_SPREAD)
            dx = c_x - x - (-uy) * off
            dy = c_y - y - (ux) * off
            dd = math.hypot(dx, dy)
            if dd < 1.0:
                continue
            _old = meas.get(mkey, {})
            meas[mkey] = {"ux": dx / dd, "uy": dy / dd, "dist": dd,
                          "size": _old.get("size", _s)}
            fixed += 1
        json.dump(meas, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n[APPLY] 回写 %d 条 → %s（备份 %s）" % (fixed, p.name, bak.name))

    print("\n[原图上找不到的] %d 个（要么摆错了，要么原图就没画）：" % len(miss))
    for key, lid, cx, cy, _g in miss:
        tag = "原图量到过" if ("%s|%s" % (lid, key)) in meas else "原图没量到"
        print("   %-22s 线%-4s (%6.0f,%6.0f)   %s" % (key, lid, cx, cy, tag))


if __name__ == "__main__":
    main()
