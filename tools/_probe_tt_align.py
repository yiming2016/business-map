# -*- coding: utf-8 -*-
"""量「首末班车」表格：表头 vs 下方内容，逐列的**是否对齐**。

为什么要有这个脚本：
    表头是一个 QGridLayout，每个分组是**另一个** QGridLayout。
    两边只有靠"列最小宽 + 末尾拉伸列"才可能对齐，肉眼看着歪却说不出歪在哪列。
    这里把每列的**中心 x** 数出来，逐列比差值，并顺便记下文字对齐方式
    （左对齐 vs 居中），因为"两个控件外框一样宽、文字一个靠左一个居中"也算错位。

用法：
    python tools/_probe_tt_align.py [站名]
    python tools/_probe_tt_align.py --compact [站名]
"""
import sys
import os

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)

from PySide6.QtCore import QPoint                     # noqa: E402
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit  # noqa: E402

from core.data_manager import get_data_manager        # noqa: E402
from ui.timetable_editor import TimetableEditor       # noqa: E402

COLS = ["圆点", "线路", "方向", "首班", "箭头", "末班"]


def collect_grids(layout, acc):
    """递归走布局树 —— QGridLayout 是**嵌套子布局**，没有自己的宿主 widget，
       所以 `findChildren + widget.layout()` 是找不到它的。"""
    if layout is None:
        return
    if isinstance(layout, QGridLayout):
        acc.append(layout)
    for i in range(layout.count()):
        it = layout.itemAt(i)
        if it is None:
            continue
        if it.layout() is not None:
            collect_grids(it.layout(), acc)
        w = it.widget()
        if w is not None and w.layout() is not None:
            collect_grids(w.layout(), acc)


def cell_center(w, root):
    """控件外框在 root 坐标系里的中心 x。"""
    p = w.mapTo(root, QPoint(0, 0))
    return p.x() + w.geometry().width() / 2.0


def grid_map(grid, root):
    """{col: [(中心x, 宽度, 控件描述)]}"""
    out = {}
    for i in range(grid.count()):
        it = grid.itemAt(i)
        w = it.widget()
        if w is None:
            continue
        pos = grid.getItemPosition(i)
        col = pos[1]
        desc = type(w).__name__
        if isinstance(w, QLabel):
            desc += f"({w.text()!r})"
        elif isinstance(w, QLineEdit):
            desc += f"({w.text()!r})"
        out.setdefault(col, []).append(
            (cell_center(w, root), w.geometry().width(), desc))
    return out


def main():
    argv = [a for a in sys.argv[1:]]
    compact = "--compact" in argv
    if "--compact" in argv:
        argv.remove("--compact")
    sid = argv[0] if argv else "机场东"

    app = QApplication.instance() or QApplication(sys.argv)
    dm = get_data_manager()
    st = dm.get_station(sid)
    if st is None or not st.get("timetable"):
        # 换一个有数据的站
        for s in dm.all_stations():
            if s.get("timetable"):
                sid, st = s.get("station_name"), s
                break
    tt = TimetableEditor(st.get("timetable") or "", compact=compact)
    # 放到一个大容器里再显示：单独 show 时可用宽不受约束，量出来是假的
    host = QLabel()
    from PySide6.QtWidgets import QVBoxLayout
    lay = QVBoxLayout(host)
    lay.addWidget(tt)
    host.resize(760 if not compact else 338, 600)
    host.show()
    app.processEvents()

    grids = []
    collect_grids(tt.layout(), grids)
    # findChildren 的顺序 = 构造顺序：第 0 个是表头，其后是各分组
    print(f"站={sid}  compact={compact}  网格数={len(grids)}（1 表头 + {len(grids)-1} 分组）")
    header = grid_map(grids[0], tt)
    print("\n表头：")
    for c in sorted(header):
        cx, wd, desc = header[c][0]
        print(f"  列{c} {COLS[c]:3s} 中心x={cx:7.1f} 宽={wd:5.1f}  {desc}")

    worst = 0.0
    # ★ 一次只显示一组（下拉切换可见性），**隐藏的控件没有真实几何** ——
    #   直接量会拿到未布局的旧坐标，全是假失败。必须切一次、布局一次、再量。
    widths_seen = []
    for gi, gr in enumerate(grids[1:], 1):
        tt.date_combo.setCurrentIndex(gi - 1)
        app.processEvents()
        header = grid_map(grids[0], tt)
        gm = grid_map(gr, tt)
        widths_seen.append([round(gm[c][0][1], 1) for c in sorted(gm)])
        print(f"\n分组{gi}（{tt.current_date()}）vs 表头"
              f"（Δ = 表头中心 − 内容中心）：")
        for c in sorted(gm):
            hm = header.get(c)
            if not hm:
                print(f"  列{c}: 表头没有这一列")
                continue
            for cx, wd, desc in gm[c]:
                d = hm[0][0] - cx
                worst = max(worst, abs(d))
                flag = "OK " if abs(d) <= 1.0 else "!! "
                print(f"  {flag}列{c} {COLS[c]:3s} Δ={d:6.1f}  "
                      f"内容宽={wd:5.1f}  {desc}")
    print(f"\n最大错位 = {worst:.1f}px")
    # ◎ 切换日期类型时列宽必须一致（否则点一下下拉，整张表会左右跳）
    uniq = {tuple(w) for w in widths_seen}
    print(f"各组列宽 = {widths_seen}")
    print("切换类型时列宽" + ("一致 ✓" if len(uniq) <= 1 else "**会跳** ✗"))

    # 顺带报告"文字对齐方式"：同一列里一边靠左一边居中，视觉上就是歪的
    print("\n文字对齐：")
    for c, name in ((1, "线路"), (2, "方向"), (3, "首班"), (5, "末班")):
        pass
    host.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
