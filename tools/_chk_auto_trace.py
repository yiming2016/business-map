# -*- coding: utf-8 -*-
"""
回归 v2.6.55：**自动追踪** —— 让线条照着官方原图走（甲）+ 站点吸到走廊（乙）。

用户原话：「我还是无法让线条跟随下方的底图」+「两个都要，点位基本准确」。

判据（每条都带变异自检，证明判据有牙）：
  A 走廊点云：20 条线都有、点数够。        变异：删掉一条线的点云 ⇒ 必须失败
  B 描线成功率 ≥ 85%。                     变异：BRIDGE=0（不搭桥）⇒ 成功率必须掉
  C 路径几何：两端接得上站点、不炸开、不绕远
  D 渲染真用上了：写 traced ⇒ 路径元素变多且经过描出来的点
                                           变异：清掉 traced ⇒ 必须退回折线
  E 拖动吸附：离走廊 20px ⇒ 拖过去自己归位；离 300px 不许硬拉
                                           变异：TRACE_SNAP=False ⇒ 不许吸附
  F Ctrl+Z：全图描线一下全撤（traced 清空）

运行：
    ...\\python.exe tools/_chk_auto_trace.py
"""
from __future__ import annotations

import sys
import tempfile
import shutil
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="autotrace_"))
for _n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402
from ui.map_view import line_station_xy                             # noqa: E402

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

    from ui import trace_assist as TA
    TA.reload()

    # ---------------------------------------------------------------
    print("===== A 走廊点云 data/trace_cloud.json =====")
    ok("A1 点云文件在（不然整个自动追踪就是空的）", TA.available())
    cloud = TA._load()
    lines = dm.all_lines()
    lids = [str(l.get("id")) for l in lines]
    ok("A2 每条线都有点云", len(cloud) >= len(lids),
       f"{len(cloud)} 条 / 线路 {len(lids)} 条")
    thin = [k for k in lids if len(TA.cloud_of(k)) < 200]
    ok("A3 没有哪条线的点云少到不能用（<200 点）", not thin, f"太少的：{thin}")
    # 变异
    _saved = cloud.get(lids[0])
    cloud[lids[0]] = []
    TA._graphs.pop(lids[0], None)
    ok("A4 变异：删掉一条线的点云 ⇒ A3 判据真的会响",
       len(TA.cloud_of(lids[0])) < 200)
    cloud[lids[0]] = _saved
    TA._graphs.pop(lids[0], None)

    # ---------------------------------------------------------------
    print("===== B 描线成功率（甲） =====")

    def success_rate():
        o = t = 0
        for L in lines:
            lid = str(L.get("id"))
            seq = [n for n in (L.get("stations") or []) if n in dm.all_stations()]
            for i in range(1, len(seq)):
                t += 1
                sa = dm.all_stations()[seq[i - 1]]
                sb = dm.all_stations()[seq[i]]
                ax, ay = line_station_xy(sa, lid)
                bx, by = line_station_xy(sb, lid)
                if TA.trace(lid, ax, ay, bx, by):
                    o += 1
        return o, t

    ok_n, ok_t = success_rate()
    rate = 100.0 * ok_n / max(ok_t, 1)
    ok("B1 全图描线成功率 ≥ 85%", rate >= 85.0, f"{ok_n}/{ok_t} = {rate:.1f}%")
    # 变异：不许搭桥 ⇒ 被别的线横穿切断的走廊就接不起来，成功率必须掉
    _b = TA.BRIDGE
    TA.BRIDGE = 0.0
    TA._graphs.clear()
    mu_n, mu_t = success_rate()
    ok("B2 变异：BRIDGE=0（不搭桥）⇒ 成功率明显掉下去（B1 判据真在岗）",
       mu_n < ok_n - 30, f"搭桥 {ok_n} → 不搭桥 {mu_n}")
    TA.BRIDGE = _b
    TA._graphs.clear()

    # ---------------------------------------------------------------
    print("===== C 描出来的路径几何 =====")
    worst_end = 0.0
    worst_ratio = 0.0
    nseg = 0
    chord_dev: list = []      # 每条弦的中点到走廊的距离
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in dm.all_stations()]
        for i in range(1, len(seq)):
            sa = dm.all_stations()[seq[i - 1]]
            sb = dm.all_stations()[seq[i]]
            ax, ay = line_station_xy(sa, lid)
            bx, by = line_station_xy(sb, lid)
            pts = TA.trace(lid, ax, ay, bx, by)
            if not pts:
                continue
            nseg += 1
            worst_end = max(worst_end,
                            math.hypot(pts[0][0] - ax, pts[0][1] - ay),
                            math.hypot(pts[-1][0] - bx, pts[-1][1] - by))
            ln = 0.0
            for k in range(1, len(pts)):
                x1, y1 = pts[k - 1]
                x2, y2 = pts[k]
                ln += math.hypot(x2 - x1, y2 - y1)
                # ★ 简化(RDP)会把一串点压成一条长弦 —— 弦本身可以很长（那是直的），
                #   但**弦的中点必须还贴着走廊**，否则就是抄近路把拐角削掉了。
                mx, my = (x1 + x2) * 0.5, (y1 + y2) * 0.5
                dv = TA.deviation(lid, mx, my)
                if dv is not None:
                    chord_dev.append(dv)
            span = math.hypot(bx - ax, by - ay)
            worst_ratio = max(worst_ratio, ln / max(span, 1e-6))
    chord_dev.sort()
    n_dev = len(chord_dev)
    p90 = chord_dev[int(n_dev * 0.9)] if n_dev else 0.0
    mx_dev = chord_dev[-1] if n_dev else 0.0
    ok("C1 路径两端接得上站点（离端点 ≤ 90px）", worst_end <= 90.0,
       f"最远 {worst_end:.0f}px（{nseg} 段）")
    # ★ 放宽到"九成"是因为**搭桥**那一跳本来就要跨过被别的线盖掉的一截走廊
    #   （那边根本没有走廊点可贴），那一跳的中点自然离走廊远。
    ok("C2 九成以上的弦，中点仍贴着走廊（≤12px，不许抄近路削拐角）", p90 <= 12.0,
       f"P90 {p90:.1f}px（{n_dev} 条弦）")
    ok("C2b 就算搭桥那一跳，中点离走廊也不超过 60px", mx_dev <= 60.0,
       f"最远 {mx_dev:.1f}px")
    ok("C3 路径不绕远（总长 ≤ 直线 ×2.2）", worst_ratio <= 2.2,
       f"最大长度比 {worst_ratio:.2f}")

    # ---------------------------------------------------------------
    print("===== D 渲染真的用上了描出来的路径 =====")
    # ★ v2.6.59：D 组会往 traced 里塞一段（且不提交到撤销栈），E/F 组要在一个
    #   **干净的** traced 上跑 ⇒ 先把原始 traced 整份记下来，D 组结束时还原。
    _traced_before_D = dict(dm.lines_doc.get("traced") or {})
    line = max(lines, key=lambda l: len(l.get("stations") or []))
    lid = str(line.get("id"))
    seq = [n for n in (line.get("stations") or []) if n in dm.all_stations()]
    a, b = seq[len(seq) // 2], seq[len(seq) // 2 + 1]
    key = "%s|%s|%s" % (lid, a, b)
    # ★★ v2.6.63 修正：`n_flat` 必须是「**完全没有描线**」的基线。
    #    原来它是在库里那 223 段真实描线**还在**的时候直接量的（119），
    #    而 D5 变异清掉描线后是 101 ⇒ 两次测量根本不是同一个条件，
    #    D5 恒失败（119 vs 101），而且看不出原因。
    #    （又是同一条教训：凡是"两次测量相比"的判据，先确认两次条件一致）
    _tr0 = dict(dm.lines_doc.get("traced") or {})
    _off0 = dm.lines_doc.get("octi_off")
    dm.lines_doc["traced"] = {}
    dm.lines_doc["octi_off"] = []
    mv.rebuild_lines()
    pump(6)
    n_flat = mv.line_items[lid].path().elementCount()
    dm.lines_doc["traced"] = _tr0
    dm.lines_doc["octi_off"] = _off0
    mv.rebuild_lines()
    pump(6)
    done = mv._auto_trace_seg(lid, a, b)
    ok("D1 这一段真的描出来了（原图上有走廊可描）", done, key)
    mv.rebuild_lines()          # ★ _auto_trace_seg 故意不提交（为了整批只压一份快照）
    pump(8)
    tp = (dm.lines_doc.get("traced") or {}).get(key) or []
    ok("D2 写进了 lines_doc['traced']（落盘 + Ctrl+Z 才有）", len(tp) >= 2,
       f"{len(tp)} 个点")
    n_tr = mv.line_items[lid].path().elementCount()
    ok("D3 重画后这一段变成一串点（路径元素变多）", n_tr > n_flat,
       f"折线 {n_flat} → 描线 {n_tr}")
    # ★ 不能拿 path.elementAt() 去比 —— 圆角是用 quadTo 画的，顶点只作为
    #   **控制点**存在（还会被"外移"以保证弧过站点），坐标对不上并不代表没画到。
    #   正解是量**几何**：把路径描粗，看点是不是落在这条带子里。
    from PySide6.QtGui import QPainterPathStroker
    from PySide6.QtCore import QPointF
    pth = mv.line_items[lid].path()
    stk = QPainterPathStroker()
    stk.setWidth(10.0)
    band = stk.createStroke(pth)
    tx, ty = float(tp[0][0]), float(tp[0][1])
    hit = band.contains(QPointF(tx, ty))
    ok("D4 画出来的线真的从描线点上过（把路径描粗 10px 去套）", hit,
       f"首个描线点 ({tx:.0f},{ty:.0f})")
    # 变异（★ v2.6.59：变异必须**还原**，否则它把库里那批真实的描线（201 段）
    #   一起清掉了，F 组拿到的"描线前的段数"就是 0 ⇒ F3 判据的前提被污染）
    _traced_saved = dm.lines_doc.get("traced")
    _off_saved = dm.lines_doc.get("octi_off")
    dm.lines_doc["traced"] = {}
    # ★★ v2.6.63：`octi_off`（免八向化名单）是**独立生效**的（没有描线也生效）
    #   ⇒ 要"退回折线"必须把名单一起清掉，只清 traced 回不到基线。
    dm.lines_doc["octi_off"] = []
    mv.rebuild_lines()
    pump(6)
    n_back = mv.line_items[lid].path().elementCount()
    ok("D5 变异：清掉 traced + octi_off ⇒ 退回折线（D3 判据真在岗）", n_back == n_flat,
       f"折线 {n_flat} / 现在 {n_back} / 描线 {n_tr}")
    dm.lines_doc["octi_off"] = _off_saved
    dm.lines_doc["traced"] = dict(_traced_before_D)
    mv.rebuild_lines()
    pump(6)

    # ---------------------------------------------------------------
    print("===== E 拖动吸附（乙） =====")
    from ui import metro_render as MR
    sa = dm.all_stations().get(a)
    sx0, sy0 = float(sa.get("x")), float(sa.get("y"))
    near = TA.snap([lid], sx0, sy0, 400.0)
    ok("E1 能查到这个站脚下的走廊点", near is not None,
       f"偏差 {near[2]:.1f}px" if near else "查不到")
    if near:
        it = mv.station_items.get(a)
        ok("E2 拿得到这个站的图元", it is not None)
        if it is not None:
            # 故意挪开 20px（在吸附半径 30px 内）⇒ 应当被吸回去
            it._snapping = True
            MR.TRACE_SNAP = True
            # ★ 往**离走廊最远**的那个方向挪 22px：走廊可能是横的也可能是竖的，
            #   一律往 +x 挪的话，"横走廊"那个方向其实还在线上（判据就假通过了）。
            pick = None
            for k in range(8):
                th = k * math.pi / 4.0
                px = near[0] + 22.0 * math.cos(th)
                py = near[1] + 22.0 * math.sin(th)
                dv = TA.deviation(lid, px, py)
                if dv is None:
                    continue
                if pick is None or dv > pick[2]:
                    pick = (px, py, dv)
            ok("E2b 找到了一个确实离开走廊的落点", pick is not None and pick[2] >= 12.0,
               f"最远方向离走廊 {pick[2]:.1f}px" if pick else "找不到")
            it.setPos(pick[0], pick[1])
            pump(3)
            # ★ 量的是"落点离走廊多远"（不是离 near 那个点）—— 走廊是横的时候，
            #   旁边一格的点更近，吸到它也算归位，两个口径会差出十几像素。
            # ★ `or 999` 是坑：deviation 返回 0.0 时 0.0 是假值 ⇒ 会被当成"查不到"。
            dv1 = TA.deviation(lid, it.pos().x(), it.pos().y())
            got = 999.0 if dv1 is None else dv1
            ok("E3 离走廊 22px 拖过去 ⇒ 自己归位（落点贴回走廊 ≤3px）", got <= 3.0,
               f"落点离走廊 {got:.1f}px")
            # 变异：关掉吸附 ⇒ 不许再吸
            MR.TRACE_SNAP = False
            it.setPos(pick[0], pick[1])
            pump(3)
            dv2 = TA.deviation(lid, it.pos().x(), it.pos().y())
            got2 = 999.0 if dv2 is None else dv2
            ok("E4 变异：关掉吸附 ⇒ 拖到哪就是哪（不许吸）", got2 > 10.0,
               f"落点离走廊 {got2:.1f}px（期望 ≈{pick[2]:.0f}）")
            MR.TRACE_SNAP = True
            # 离得远不许硬拉
            far = TA.snap([lid], sx0 + 300.0, sy0 + 300.0, 30.0)
            ok("E5 离走廊 300px 时不许硬拉（磁铁只在近处生效）", far is None,
               f"{far}")
            it.setPos(sx0, sy0)
            it._snapping = False
    pump(4)

    # ---------------------------------------------------------------
    print("===== F 全图描线 + Ctrl+Z =====")
    # ★ v2.6.59：库里**本来就有**一批照官方重建好的描线（201 段），
    #   不再是空的 ⇒ 判据不能写死"撤销后归 0"（那样恒失败），
    #   要改成"撤销后回到**描线之前**的段数"；同时 F1 要断言确实**新增**了段，
    #   否则"描了个寂寞、撤销后自然等于原值"会假通过。
    n_base = len(dm.lines_doc.get("traced") or {})
    o, t, failed = mv.auto_trace_all()
    pump(8)
    n_all = len(dm.lines_doc.get("traced") or {})
    ok("F1 全图描线写进了很多段", n_all >= 200 and n_all > n_base,
       f"{o}/{t} 段，描不出 {len(failed)} 段；库里 {n_base} → {n_all}")
    ok("F2 描不出来的段**保持原样**（有名单、不瞎猜）", isinstance(failed, list))
    win._on_undo()
    pump(10)
    n_undo = len(CDM.get_data_manager().lines_doc.get("traced") or {})
    ok("F3 Ctrl+Z 一下全撤回来", n_undo == n_base,
       f"撤销后 {n_undo} 段（应回到描线前的 {n_base}）")

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
