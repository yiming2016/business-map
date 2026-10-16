# -*- coding: utf-8 -*-
"""回归 v2.6.24 的「45° 斜线贴哪一头」（用户原话：弯曲方向和原图相反）。

四组判据：
  A 数据有内容          —— elbow_sides.json 不能是空表、"b" 不能只有两三条；
  B 程序真在用          —— 带 elbows 画出来的路径，得跟"一律 a"的路径**真的不一样**；
  C 变异自检            —— METROEDITOR_NO_ELBOW_FIX=1 ⇒ 退回空表 + 路径完全等于"一律 a"；
  D 照原图              —— 重新拿原图的距离场判一遍，跟记在表里的方向对得上
                          （★ 这一段**故意自己再算一遍**，不复用 measure 脚本的函数：
                            复用就等于"拿被测代码验被测代码"，改坏了也验不出来）。
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QPointF                     # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from core.data_manager import get_data_manager         # noqa: E402
from ui.map_view import (elbow_sides, load_elbow_sides,
                         build_line_points_ex, line_station_xy)   # noqa: E402
from ui.metro_render import (build_octilinear_path,
                             octilinear_waypoints_tagged)   # noqa: E402

OK, BAD = [], []


def check(desc, cond, detail=""):
    (OK if cond else BAD).append(desc)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", desc,
                           ("   （%s）" % detail) if detail else ""))


def hex2rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def path_sig(pts, elbows=None):
    """把路径压成"可比较的字符串"，用来判两段路径是不是真不一样。"""
    p = build_octilinear_path(pts, 170.0, elbows)
    return "|".join("%.1f,%.1f" % (p.elementAt(i).x, p.elementAt(i).y)
                    for i in range(p.elementCount()))


def df_side(img, rgb, a, b, m, sx, sy):
    """拿原图距离场判这一段该用 "a" 还是 "b"。返回 (side, 差值)；判不出返回 None。"""
    (ax, ay), (bx, by) = a, b
    x0, x1 = int(min(ax, bx)) - 110, int(max(ax, bx)) + 110
    y0, y1 = int(min(ay, by)) - 110, int(max(ay, by)) + 110
    H, W = img.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    r, g, bb = rgb
    msk = (np.abs(sub[:, :, 0] - r) + np.abs(sub[:, :, 1] - g)
           + np.abs(sub[:, :, 2] - bb)) <= 30
    if msk.sum() < 200:
        return None
    # 距离场：每个像素到**最近的该线颜色像素**的距离
    dt = ndimage.distance_transform_edt(~ndimage.binary_erosion(msk, np.ones((3, 3))))

    cand = {
        "a": [(ax, ay), (ax + sx * m, ay + sy * m), (bx, by)],
        "b": [(ax, ay), (bx - sx * m, by - sy * m), (bx, by)],
    }
    score = {}
    for k, poly in cand.items():
        vals = []
        for i in range(len(poly) - 1):
            (px, py), (qx, qy) = poly[i], poly[i + 1]
            L = ((qx - px) ** 2 + (qy - py) ** 2) ** 0.5
            n = max(int(L / 4.0), 1)
            for t in range(n + 1):
                f = t / float(n)
                sx_, sy_ = px + (qx - px) * f, py + (qy - py) * f
                # 两端各掐掉 46px（站点图标/圆角区不参与比较）
                d0 = ((sx_ - px) ** 2 + (sy_ - py) ** 2) ** 0.5 + i * L
                d1 = L * (len(poly) - 1) - d0
                if d0 < 46 or d1 < 46:
                    continue
                yy, xx = int(round(sy_)) - y0, int(round(sx_)) - x0
                if 0 <= yy < dt.shape[0] and 0 <= xx < dt.shape[1]:
                    vals.append(dt[yy, xx])
        if not vals:
            return None
        score[k] = float(np.mean(vals))
    diff = abs(score["a"] - score["b"])
    if diff < 1.0:
        return None
    return ("a" if score["a"] < score["b"] else "b"), diff


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841
    dm = get_data_manager()
    stations = dm.all_stations()

    print("\n===== A：数据有内容 =====")
    eb = elbow_sides()
    nb = sum(1 for v in eb.values() if v == "b")
    na = sum(1 for v in eb.values() if v == "a")
    check("elbow_sides.json 至少 40 段", len(eb) >= 40, "%d 段" % len(eb))
    check("里面 'b' 至少 20 段（不是随手写的空表）", nb >= 20, "b=%d a=%d" % (nb, na))

    print("\n===== B：程序真在用它（折点必须真的动） =====")
    diff_wp = 0
    diff_lines = 0
    total_lines = 0
    for line in dm.all_lines():
        lid = str(line["id"])
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        pts, ebl = build_line_points_ex(lid, seq, stations)
        if len(pts) < 2:
            continue
        total_lines += 1
        w_on = octilinear_waypoints_tagged(pts, ebl)
        w_off = octilinear_waypoints_tagged(pts, ["a"] * len(pts))
        d = sum(1 for u, v in zip(w_on, w_off)
                if abs(u[0].x() - v[0].x()) > 0.5 or abs(u[0].y() - v[0].y()) > 0.5)
        diff_wp += d
        if d:
            diff_lines += 1
    check("至少 20 个折点因这张表而挪位", diff_wp >= 20, "%d 个折点" % diff_wp)
    check("至少 8 条线的走向因此改变", diff_lines >= 8,
          "%d / %d 条线" % (diff_lines, total_lines))

    print("\n===== C：变异自检（开关一开必须完全退回老画法） =====")
    os.environ["METROEDITOR_NO_ELBOW_FIX"] = "1"
    check("开关打开后 load_elbow_sides() 返回空表", load_elbow_sides() == {})
    same = 0
    for line in dm.all_lines():
        lid = str(line["id"])
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        pts, _ = build_line_points_ex(lid, seq, stations)
        if len(pts) < 2:
            continue
        if path_sig(pts, ["a"] * len(pts)) == path_sig(pts, [""] * len(pts)):
            same += 1
    check("空表（缺省 a）与显式全 a 的路径完全一致 ⇒ B 判据测的真是这张表",
          same == total_lines, "%d / %d" % (same, total_lines))
    os.environ.pop("METROEDITOR_NO_ELBOW_FIX", None)

    print("\n===== D：照原图再判一遍（自己算，不复用测量脚本） =====")
    img = np.asarray(Image.open(SRC / "assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
    agree = disagree = unknown = 0
    flip_agree = 0
    checked = 0
    for line in dm.all_lines():
        lid = str(line["id"])
        rgb = hex2rgb(line.get("color", "#888888"))
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        # ★ 必须用**真正画出来的点段**（含走廊偏移 + 替身点）去跟原图比，
        #   不能拿"站到站的直线"比 —— 第一版就是这么写的，一致率只有 8%，
        #   因为比的根本不是同一条线。
        pts, _e, keys = build_line_points_ex(lid, seq, stations, want_keys=True)
        for i in range(1, len(pts)):
            key = keys[i] if i < len(keys) else ""
            want = eb.get(key)
            if want not in ("a", "b"):
                continue
            ax, ay = float(pts[i - 1].x()), float(pts[i - 1].y())
            bx, by = float(pts[i].x()), float(pts[i].y())
            dx, dy = bx - ax, by - ay
            adx, ady = abs(dx), abs(dy)
            big = max(adx, ady)
            if big < 1e-6 or adx < 1e-6 or ady < 1e-6:
                continue
            if abs(adx - ady) <= big * 0.08:
                continue
            m = min(adx, ady)
            if m < 30:                       # 太短的段不参与（站点图标区）
                continue
            got = df_side(img, rgb, (ax, ay), (bx, by), m,
                          1.0 if dx > 0 else -1.0, 1.0 if dy > 0 else -1.0)
            if got is None:
                unknown += 1
                continue
            checked += 1
            if got[0] == want:
                agree += 1
            else:
                disagree += 1
            flip_agree += 1 if got[0] == "a" else 0
    rate = agree / float(max(checked, 1))
    check("表里记的方向与原图一致率 ≥ 80%%", rate >= 0.80,
          "%d/%d = %.0f%%（分不出 %d）" % (agree, checked, rate * 100, unknown))
    # ★ 变异自检：把表全翻成 "a"，一致率必须明显掉下去
    check("变异（表里方向全当 a）后一致率明显更低 ⇒ D 判据真在上岗",
          (flip_agree / float(max(checked, 1))) < rate - 0.15,
          "全 a 时 %.0f%% vs 实际 %.0f%%" % (flip_agree / float(max(checked, 1)) * 100,
                                             rate * 100))

    print("\n" + "=" * 62)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  失败：%s" % b)
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
