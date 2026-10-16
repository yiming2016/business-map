# -*- coding: utf-8 -*-
"""
回归 v2.6.62：Ctrl + 光标停在某段线路上 ⇒ 双击/右键弹"这一段"的菜单。

用户原话：「按住ctrl后，光标位于两个站点之间的线路，则双击/右键可以触发菜单。
菜单内容包含'转为直线、探测弧度'」。

判据（每条都带变异自检，证明判据有牙 —— 不然就是恒真的摆设）：
  A 命中：段上的点 ⇒ `_seg_at` 找到这一段；阈值归零 ⇒ **必须**找不到
  B 体检：每段都量得出 dev_now / dev_line / dev_arc
  C 存在"官方真弯"的段：弧度明显优于直线（否则"探测弧度"这项没意义）
                                            变异：trace_smooth 退化成直连 ⇒ 必须失败
  D 转为直线：traced / segment_shapes 里的这一段被删掉，渲染点列变短
  E 探测弧度：写进 traced，且**离底图不许变差**（自检）
  F 自检有牙：喂一条绕远 400px 的假弧 ⇒ 必须被自检拦下、不写盘
                                            变异：cloud_dev 恒返回 0 ⇒ 必须失败

运行：
    ...\\python.exe tools/_chk_seg_menu.py
"""
from __future__ import annotations

import math
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="segmenu_"))
for _n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPointF                                   # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402
from ui.main_window import MainWindow                                # noqa: E402
from ui.map_view import line_station_xy, build_line_points_ex        # noqa: E402
from ui import trace_assist as TA                                    # noqa: E402

PASS = 0
FAIL = 0


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def seg_key(lid, a, b):
    return "%s|%s|%s" % (lid, a, b)


def render_len(mv, lid, a, b):
    """这一段真正画出来用了几个顶点。"""
    dm = CDM.get_data_manager()
    pts, _ = build_line_points_ex(lid, [a, b], dm.all_stations())
    return len(pts)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    mv = win.map_view
    dm = CDM.get_data_manager()
    st = dm.all_stations()

    if not TA.available():
        print("  [FAIL] 官方点云 trace_cloud.json 不存在，整组判据无从谈起")
        return

    # 收集候选段（只取前若干条线，控制耗时）
    cands = []
    for L in (dm.lines_doc.get("lines") or []):
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        for i in range(1, len(seq)):
            cands.append((lid, seq[i - 1], seq[i]))
    print(f"\n全图共 {len(cands)} 段，抽前 40 段做体检\n")
    sample = cands[:40]

    # ---------------- A 命中 ----------------
    print("A 组：Ctrl + 光标停在线上 ⇒ 能定位到那一段")
    hit_ok = 0
    for lid, a, b in sample[:12]:
        ax, ay = line_station_xy(st[a], lid)
        bx, by = line_station_xy(st[b], lid)
        mid = QPointF((ax + bx) / 2.0, (ay + by) / 2.0)
        got = mv._seg_at(mid)
        if got is not None and got[0] == lid:
            hit_ok += 1
    ok("A1 段中点能被定位到（≥10/12）", hit_ok >= 10, f"{hit_ok}/12")
    got0 = mv._seg_at(QPointF((st[sample[0][1]].get("x", 0) + st[sample[0][2]].get("x", 0)) / 2.0,
                              (st[sample[0][1]].get("y", 0) + st[sample[0][2]].get("y", 0)) / 2.0),
                      0.0)
    ok("A2 变异：命中阈值归零 ⇒ 必须找不到（证明 A1 不是恒真）", got0 is None)

    # ---------------- B/C 体检 ----------------
    print("\nB/C 组：每段都量得出数字，且存在「官方真弯」的段")
    reports = {}
    for lid, a, b in sample:
        ax, ay = line_station_xy(st[a], lid)
        bx, by = line_station_xy(st[b], lid)
        cur = (dm.lines_doc.get("traced") or {}).get(seg_key(lid, a, b))
        r = TA.seg_report(lid, ax, ay, bx, by, cur)
        reports[(lid, a, b)] = r
    good = [r for r in reports.values()
            if r["dev_now"] is not None and r["dev_line"] is not None
            and r["dev_arc"] is not None]
    ok("B1 三种画法都量得出离底图多远（≥90%）",
       len(good) >= int(0.9 * len(sample)), f"{len(good)}/{len(sample)}")
    bend = [r for r in good if r["dev_arc"] is not None and r["dev_line"] is not None
            and r["dev_line"] - r["dev_arc"] > 8.0]
    ok("C1 存在官方真弯的段：弧度明显比直线贴合（差 >8px）",
       len(bend) >= 3, f"{len(bend)} 段，最大差 "
       f"{max((r['dev_line'] - r['dev_arc']) for r in bend):.1f}px" if bend else "0 段")

    # 变异：trace_smooth 退化成 A→B 直连 ⇒ 弧度不再优于直线 ⇒ C1 必须失败
    _before = TA.trace_smooth

    def fake_straight(lid, ax, ay, bx, by, max_r=260.0):
        return [(float(ax), float(ay)), (float(bx), float(by))]

    TA.trace_smooth = fake_straight
    bend_fake = 0
    for lid, a, b in list(reports)[:20]:
        ax, ay = line_station_xy(st[a], lid)
        bx, by = line_station_xy(st[b], lid)
        cur = (dm.lines_doc.get("traced") or {}).get(seg_key(lid, a, b))
        r = TA.seg_report(lid, ax, ay, bx, by, cur)
        if (r["dev_line"] is not None and r["dev_arc"] is not None
                and r["dev_line"] - r["dev_arc"] > 8.0):
            bend_fake += 1
    TA.trace_smooth = _before
    ok("C2 变异：探测弧度退化成直连 ⇒ C1 必须失败（证明判据有牙）",
       bend_fake == 0, f"变异后仍判出 {bend_fake} 段")

    if bend:
        worst = max(bend, key=lambda r: r["dev_line"] - r["dev_arc"])
        k = [key for key, r in reports.items() if r is worst][0]
    else:
        k = sample[0]
    lid, a, b = k
    print(f"\n  挑最弯的一段做 D/E：{lid}号线 {a} → {b}"
          f"（直线 {reports[k]['dev_line']:.1f}px / 弧度 {reports[k]['dev_arc']:.1f}px）")

    # ---------------- D 转为直线 ----------------
    print("\nD 组：「转为直线」")
    ax, ay = line_station_xy(st[a], lid)
    bx, by = line_station_xy(st[b], lid)
    key = seg_key(lid, a, b)
    # 先给它一段描线，才有东西可"转直"
    if not (dm.lines_doc.get("traced") or {}).get(key):
        mv._auto_trace_seg(lid, a, b)
        mv._commit_data()
        pump(4)
    n_before = render_len(mv, lid, a, b)
    mv._apply_seg_straight(lid, a, b)
    pump(4)
    n_after = render_len(mv, lid, a, b)
    ok("D1 traced 里这一段被删掉",
       key not in (dm.lines_doc.get("traced") or {}))
    ok("D2 弧形状（cup/cap）也被清掉",
       key not in (dm.lines_doc.get("segment_shapes") or {}))
    ok("D3 渲染顶点确实变少了（不再绕）", n_after < n_before,
       f"{n_before} → {n_after}")

    # ---------------- E 探测弧度 ----------------
    print("\nE 组：「探测弧度」+ 自检")
    dev_before = TA.cloud_dev(lid, [(ax, ay), (bx, by)])
    mv._apply_seg_arc(lid, a, b)
    pump(4)
    got = (dm.lines_doc.get("traced") or {}).get(key)
    ok("E1 探测出来的点列写进了 traced", isinstance(got, list) and len(got) >= 2,
       f"{len(got) if got else 0} 个点")
    if got:
        dev_after = TA.cloud_dev(lid, [tuple(p[:2]) for p in got])
        ok("E2 探测后**离底图不许变差**（自检）",
           dev_after is None or dev_before is None or dev_after <= dev_before + 3.0,
           f"{dev_before:.1f} → {dev_after:.1f} px")
        ok("E3 贴底图程度优于直连", dev_after is not None and dev_after < dev_before,
           f"{dev_before:.1f} → {dev_after:.1f} px")

    # ---------------- F 自检有牙 ----------------
    print("\nF 组：喂一条绕远 400px 的假弧 ⇒ 必须被自检拦下")

    def fake_bad(lid_, ax_, ay_, bx_, by_, max_r=260.0):
        mx, my = (ax_ + bx_) / 2.0, (ay_ + by_) / 2.0
        dx, dy = bx_ - ax_, by_ - ay_
        L = math.hypot(dx, dy) or 1.0
        return [(mx - dy / L * 400.0, my + dx / L * 400.0)]

    dm.lines_doc.setdefault("traced", {})[key] = [[ax, ay], [bx, by]]
    _b2 = TA.trace_smooth
    TA.trace_smooth = fake_bad
    mv._apply_seg_arc(lid, a, b, None)
    pump(4)
    written = (dm.lines_doc.get("traced") or {}).get(key)
    TA.trace_smooth = _b2
    ok("F1 绕远的假弧被自检拦下，没有写进 traced",
       written == [[ax, ay], [bx, by]], f"现在是 {written}")

    _b3 = TA.cloud_dev

    def fake_zero(line_id, pts):
        return 0.0

    TA.cloud_dev = fake_zero
    TA.trace_smooth = fake_bad
    mv._apply_seg_arc(lid, a, b, None)
    pump(4)
    written2 = (dm.lines_doc.get("traced") or {}).get(key)
    TA.trace_smooth = _b2
    TA.cloud_dev = _b3
    ok("F2 变异：cloud_dev 恒返回 0（自检瞎了）⇒ F1 必须失败",
       written2 != [[ax, ay], [bx, by]], f"现在是 {written2}")

    print(f"\n{'=' * 60}\n合计：{PASS} 通过 / {FAIL} 失败\n{'=' * 60}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
