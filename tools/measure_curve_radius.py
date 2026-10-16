# -*- coding: utf-8 -*-
"""只读：量原图线路**拐弯处那道弧**的半径（场景单位 == 原图像素）。

用法:
    python tools/measure_curve_radius.py [采样上限]

做法：
  1. 用 build_line_points_ex 取出真正画出来的点列，找方向变化的拐点；
  2. 在原图上取**该线颜色**的掩膜（容差 48），局部窗口内取中心线
     （distance_transform_edt ≥ 线宽一半×0.75 的像素就是线的中轴）；
  3. 对中轴点集**最小二乘拟合圆**，半径即该处弧的半径。
     ★ 残差 rmse 是"这里到底是不是一段正圆弧"的证据 —— rmse 大的（窗口里
       混进了长直线）直接丢掉，不能拿它当结论。
"""
import os
import sys
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                    # noqa: E402
from PIL import Image                                 # noqa: E402
from scipy import ndimage                             # noqa: E402
from scipy.optimize import least_squares              # noqa: E402

from PySide6.QtWidgets import QApplication            # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841

from ui.map_view import build_line_points_ex          # noqa: E402

IMG = ROOT / "assets" / "shenzhen_metro.png"
WIN = int(os.environ.get("RAD_WIN", "150"))     # 局部窗口半边长
TOL = int(os.environ.get("RAD_TOL", "48"))      # 颜色容差
HALF_W = 11.0                                   # 原图线宽一半


def hex2rgb(h):
    h = (h or "").lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def fit_radius(arr, color, cx, cy, win=WIN):
    H, W, _ = arr.shape
    x0, y0 = max(0, int(cx) - win), max(0, int(cy) - win)
    x1, y1 = min(W, int(cx) + win), min(H, int(cy) + win)
    sub = arr[y0:y1, x0:x1].astype(np.int16)
    d = np.abs(sub - np.array(color, dtype=np.int16)).sum(axis=2)
    mask = d < TOL
    if mask.sum() < 300:
        return None
    dt = ndimage.distance_transform_edt(mask)
    core = mask & (dt >= HALF_W * 0.75)
    ys, xs = np.nonzero(core)
    if len(xs) < 60:
        return None
    X = xs.astype(float) + x0
    Y = ys.astype(float) + y0

    def resid(p):
        a, b, r = p
        return np.sqrt((X - a) ** 2 + (Y - b) ** 2) - r

    best = None
    for r0 in (60.0, 150.0, 300.0, 600.0):
        sol = least_squares(resid, [cx, cy, r0], method="lm", max_nfev=400)
        a, b, r = sol.x
        rmse = float(np.sqrt(np.mean(sol.fun ** 2)))
        # 圆心必须落在窗口附近（否则是在拟合一条直线 ⇒ r 会飞到几万）
        if math.hypot(a - cx, b - cy) > win * 1.6:
            continue
        if best is None or rmse < best[1]:
            best = (r, rmse, (a, b))
    if best is None:
        return None
    return best[0], best[1], best[2], len(xs)


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    st = json.load(open(ROOT / "data" / "stations.json", encoding="utf-8"))["stations"]
    ln = json.load(open(ROOT / "data" / "lines.json", encoding="utf-8"))
    lines = ln["lines"] if isinstance(ln, dict) and "lines" in ln else ln
    print("[IMG] %s" % IMG)
    arr = np.asarray(Image.open(IMG).convert("RGB"))
    print("[IMG] %dx%d" % (arr.shape[1], arr.shape[0]))

    # 收集拐点
    corners = []
    for L in lines:
        lid = str(L.get("id") or L.get("line_id") or "")
        seq = L.get("stations") or []
        color = hex2rgb(L.get("color"))
        if len(seq) < 3:
            continue
        try:
            pts, _ebl = build_line_points_ex(lid, seq, st)
        except Exception as e:
            print("  [SKIP] 线 %s: %s" % (lid, e))
            continue
        for i in range(1, len(pts) - 1):
            v1 = (pts[i].x() - pts[i - 1].x(), pts[i].y() - pts[i - 1].y())
            v2 = (pts[i + 1].x() - pts[i].x(), pts[i + 1].y() - pts[i].y())
            n1 = math.hypot(*v1)
            n2 = math.hypot(*v2)
            if n1 < 1 or n2 < 1:
                continue
            cosv = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
            cosv = max(-1.0, min(1.0, cosv))
            turn = math.degrees(math.acos(cosv))
            if turn > 8.0:
                corners.append((lid, color, pts[i].x(), pts[i].y(), turn))
    print("[拐点] 共 %d 个，采样前 %d 个" % (len(corners), min(lim, len(corners))))

    step = max(1, len(corners) // lim)
    sample = corners[::step][:lim]

    out = []
    for lid, color, x, y, turn in sample:
        got = fit_radius(arr, color, x, y)
        if not got:
            continue
        r, rmse, c, npx = got
        out.append((rmse, lid, x, y, turn, r, npx))
        print("  %-4s (%6.0f,%6.0f) 转%.0f°  半径=%8.1f  rmse=%5.2f  n=%d"
              % (lid, x, y, turn, r, rmse, npx))

    good = [o for o in out if o[0] <= 3.0]
    good.sort()
    if good:
        rs = sorted(o[5] for o in good)
        print("\n[结论] rmse≤3 的 %d 个（确实是圆弧的）：" % len(rs))
        print("   半径 min=%.0f  中位=%.0f  平均=%.0f  max=%.0f"
              % (rs[0], rs[len(rs) // 2], sum(rs) / len(rs), rs[-1]))
        print("   分布：" + ", ".join("%.0f" % v for v in rs[:30]))
    else:
        print("\n[结论] 没有 rmse≤3 的样本 —— 窗口里混进了直线，调小 RAD_WIN 再试")


if __name__ == "__main__":
    main()
