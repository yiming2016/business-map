# -*- coding: utf-8 -*-
"""
回归 v2.6.53：Ctrl 点两个站 ⇒ 右键编辑这两站之间的线路（水平 / 垂直 / 凸弧 / 凹弧）。

用户原话：「添加逻辑按住ctrl，鼠标点击两个站点后，右键可以弹出对线路编辑的选项，
水平、垂直、凸弧、凹弧」+「站点跟着挪动，第二个点击的是被动挪的，
即第一个站点不动，第二个站点挪到相对于第一个站点水平、垂直的方向」。

判据：
  A 找"这两站在哪条线上相邻"（返回**数据里的顺序**，不是点击顺序）
  B 水平 / 垂直：**第一个站不动**，第二个站挪到与它齐平
  C 凸弧 / 凹弧：写进 lines_doc["segment_shapes"]，重画后这段真的变成一串采样点
  D Ctrl+Z 能撤销（坐标和弧都要回得来）
  E 变异：不写 segment_shapes ⇒ 弧不生效（C 判据真在岗）

运行：
    ...\\python.exe tools/_chk_segment_edit.py
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="segedit_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

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


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    mv = win.map_view

    dm = CDM.get_data_manager()
    lines = dm.all_lines()
    # 挑一条站数最多的线，保证一定找得到相邻两站
    line = max(lines, key=lambda l: len(l.get("stations") or []))
    lid = str(line.get("id"))
    seq = line.get("stations") or []
    a, b = seq[len(seq) // 2], seq[len(seq) // 2 + 1]
    sa = dm.all_stations().get(a)
    sb = dm.all_stations().get(b)
    print(f"===== 用例：{lid} 号线  {a} → {b} =====")

    # ---------------------------------------------------------------
    print("===== A 找到这两站在哪条线上相邻 =====")
    cands = mv._lines_with_adjacent(a, b)
    ok("A1 相邻两站能定位到线路", any(c[0] == lid for c in cands),
       f"{len(cands)} 条候选：{[c[0] for c in cands]}")
    hit = [c for c in cands if c[0] == lid]
    ok("A2 返回的是**数据里的真实顺序**（不是点击顺序）",
       bool(hit) and (hit[0][1], hit[0][2]) == (a, b), f"{hit[0] if hit else '-'}")
    ok("A3 反过来点也能认出来（b 先 a 后）",
       any((c[1], c[2]) == (a, b) for c in mv._lines_with_adjacent(b, a)))
    ok("A4 不相邻的两站 ⇒ 返回空（不给编辑）",
       mv._lines_with_adjacent(seq[0], seq[-1]) == [] if len(seq) > 3 else True)

    # ---------------------------------------------------------------
    print("===== B 水平 / 垂直：第一个站不动，第二个站挪 =====")
    ay0, ax0 = float(sa["y"]), float(sa["x"])
    by0, bx0 = float(sb["y"]), float(sb["x"])
    mv._apply_segment_shape(lid, a, b, "h", a, b)
    pump(6)
    ok("B1 水平 ⇒ 第二个站的 y 挪到与第一个站齐平",
       abs(float(sb["y"]) - ay0) < 1e-6, f"{by0:.1f} → {sb['y']:.1f}（目标 {ay0:.1f}）")
    ok("B2 水平 ⇒ **第一个站的坐标一动不动**",
       abs(float(sa["y"]) - ay0) < 1e-6 and abs(float(sa["x"]) - ax0) < 1e-6)
    ok("B3 水平 ⇒ 第二个站的 x 保持原样（只挪 y）",
       abs(float(sb["x"]) - bx0) < 1e-6, f"{bx0:.1f} → {sb['x']:.1f}")
    mv._apply_segment_shape(lid, a, b, "v", a, b)
    pump(6)
    ok("B4 垂直 ⇒ 第二个站的 x 挪到与第一个站对齐",
       abs(float(sb["x"]) - ax0) < 1e-6, f"{bx0:.1f} → {sb['x']:.1f}（目标 {ax0:.1f}）")

    # 反过来：让 b 当基准（先点 b），应该是 a 被动挪
    sa["y"], sb["y"] = ay0, by0          # 复位
    sa["x"], sb["x"] = ax0, bx0
    mv._apply_segment_shape(lid, a, b, "h", b, a)
    pump(6)
    ok("B5 换序点（先点 b）⇒ 变成 **a** 被动挪到与 b 齐平",
       abs(float(sa["y"]) - by0) < 1e-6 and abs(float(sb["y"]) - by0) < 1e-6,
       f"a.y {ay0:.1f} → {sa['y']:.1f}（目标 {by0:.1f}）")
    sa["y"], sa["x"] = ay0, ax0
    sb["y"], sb["x"] = by0, bx0

    # ---------------------------------------------------------------
    print("===== C 凸弧 / 凹弧：写到 lines_doc 并真的画成弧 =====")
    mv.rebuild_lines()
    pump(6)
    n_flat = mv.line_items[lid].path().elementCount()
    mv._apply_segment_shape(lid, a, b, "cup", a, b)
    pump(8)
    seg = dm.lines_doc.get("segment_shapes") or {}
    ok("C1 凸弧写进了 lines_doc['segment_shapes']",
       seg.get("%s|%s|%s" % (lid, a, b)) == "cup", f"{seg}")
    n_arc = mv.line_items[lid].path().elementCount()
    ok("C2 重画后这一段真的变成一串采样点（路径元素变多）",
       n_arc > n_flat, f"直 {n_flat} → 弧 {n_arc}")
    mv._apply_segment_shape(lid, a, b, "cap", a, b)
    pump(8)
    ok("C3 凹弧也能写进去（同一个键被改写）",
       (dm.lines_doc.get("segment_shapes") or {}).get("%s|%s|%s" % (lid, a, b)) == "cap")
    ok("C4 凸弧/凹弧**不动站点坐标**",
       abs(float(sa["y"]) - ay0) < 1e-6 and abs(float(sb["y"]) - by0) < 1e-6,
       f"a.y={sa['y']:.1f} b.y={sb['y']:.1f}")

    # ---------------------------------------------------------------
    print("===== D Ctrl+Z 撤销 =====")
    mv._apply_segment_shape(lid, a, b, "h", a, b)
    pump(6)
    moved_y = float(sb["y"])
    ok("D1 先确认改动生效过（b.y 被挪走了）", abs(moved_y - by0) > 1e-6,
       f"{by0:.1f} → {moved_y:.1f}")
    win._on_undo()
    pump(10)
    # ★★ 撤销是"整份 doc 深拷贝替换"⇒ 之前拿到的 `sb` 引用**已经失效**，
    #   必须重新取一次。用旧引用去断言会得到假失败（看着像撤销没生效）。
    sb2 = dm.all_stations().get(b)
    ok("D2 撤销后坐标回到原位", sb2 is not None and abs(float(sb2["y"]) - by0) < 1e-6,
       f"撤销后 b.y={sb2['y'] if sb2 else '?':.1f}（原 {by0:.1f}，改后 {moved_y:.1f}）")
    ok("D3 撤销确实换了新 doc（旧引用已失效，不是原地改）", sb2 is not sb)

    # ---------------------------------------------------------------
    print("===== E 变异：不写 segment_shapes ⇒ 弧必须不生效 =====")
    dm.lines_doc["segment_shapes"] = {}
    mv.rebuild_lines()
    pump(6)
    n2 = mv.line_items[lid].path().elementCount()
    ok("E1 清掉 segment_shapes ⇒ 路径元素数回到折线水平（C2 判据真在岗）",
       n2 == n_flat, f"直 {n_flat} / 现在 {n2} / 弧 {n_arc}")

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
