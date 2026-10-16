# -*- coding: utf-8 -*-
"""
_chk_geom_change_order.py —— 回归：「prepareGeometryChange() 必须先于改状态」。

★★ 这条回归守的是一个**会让整个程序直接崩掉**的坑（v2.6.0 修）。

    站点图元的 boundingRect() 依赖一堆状态：_label_side（站名方向）、
    _view_scale（屏幕恒定尺寸换算）、_hover / _selected（半径变大）、
    is_transfer、以及站名文字本身。

    Qt 要求：**改这些状态之前**先调 prepareGeometryChange()，好让场景的
    BSP 索引把按"旧矩形"插进去的节点摘掉。顺序写反了（先改状态、后声明），
    Qt 就会拿着**新矩形**去索引里找**旧矩形**插的节点 —— 找不到，那个节点
    就留在树里变成僵尸项。等图元被删除（保存/导入时 reload_stations 会
    重建全部 379 个站点图元），索引里剩下的就是**野指针**；下一次重绘
    （哪怕场景已经空了）一遍历树就：
        Windows fatal exception: access violation
    进程直接没了，没有任何 Python 异常可catch。

    最难的地方在于：**崩在别处、崩在很久以后**。
    改完 label side 的那一刻一切都正常，要等到"保存/导入触发重建 + 下一次
    重绘"才炸 —— 所以必须有一条回归专门钉住顺序，不能靠"跑一遍没崩"。

判据：
  F1 运行时判据（不依赖崩溃）：包装 prepareGeometryChange，记录"声明那一刻
     看到的矩形"；每个会改几何的方法，它必须等于"改动前的矩形"。
     写反了两者就不等 —— 而且是**当场**就能发现，不用等崩。
  F2 子进程走完整路径：改 379 个图元的几何 → 全部删除 → 重绘，退出码 0。
  F3 变异：把 set_label_side 还原成旧的错误顺序，子进程必须崩（退出码 != 0）
     —— 用来证明这条回归真的抓得住。

运行：
    python tools/_chk_geom_change_order.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS = FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


# ======================================================================
# 旧的错误写法（变异用）：先改 _label_side，后声明几何变化
# ======================================================================
def old_set_label_side(self, side: str) -> None:
    self._sprite = None
    if side not in self.LABEL_SIDES_MOD or side == self._label_side:
        if side == self._label_side:
            self._layout_label()
            return
        side = "right"
    self._label_side = side          # ← 先改（boundingRect 已经变了）
    self.prepareGeometryChange()     # ← 后声明（此刻读到的是新矩形）
    self._layout_label()
    self.update()


# ======================================================================
# 子进程：跑"改几何 → 删图元 → 重绘"
# ======================================================================
def child_main(mutate: bool) -> int:
    import core.data_manager as DM
    from ui.main_window import MainWindow
    from ui import metro_render as MR
    from PySide6.QtWidgets import QApplication

    if mutate:
        MR.StationDotItem.LABEL_SIDES_MOD = MR.LABEL_SIDES
        MR.StationDotItem.set_label_side = old_set_label_side

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="chk_geom_"))
    DM.STATIONS_FILE = tmp / "stations.json"
    DM.LINES_FILE = tmp / "lines.json"

    mv = win.map_view
    # ① 改几何：站名换边（这正是"单独显示某条线"重排站名时做的事）
    for it in mv.station_items.values():
        it.set_label_side("left")
    app.processEvents()

    # ② 删图元：保存/导入就是这么干的（reload_stations 先全删再全建）
    for k in list(mv.station_items.keys()):
        mv.scene_.removeItem(mv.station_items.pop(k))

    # ③ 重绘：崩就崩在这一步
    mv.viewport().grab()
    print("CHILD SURVIVED", flush=True)
    return 0


def run_child(mutate: bool) -> int:
    """在子进程里跑，免得父进程被崩掉之后打不出报告。"""
    args = [sys.executable, str(Path(__file__).resolve()), "--child"]
    if mutate:
        args.append("--mutate-old-order")
    p = subprocess.run(args, capture_output=True, text=True, timeout=180)
    tail = (p.stdout or "").strip().splitlines()
    return p.returncode, (tail[-1] if tail else "")


# ======================================================================
# 父进程
# ======================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--mutate-old-order", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:
        return child_main(args.mutate_old_order)

    print("=" * 78)
    print("回归：prepareGeometryChange() 必须先于一切会改变 boundingRect() 的改动")
    print("=" * 78)

    # ---------------- F1：运行时判据（当场发现，不用等崩） ----------------
    print("\nF1 组：声明几何变化那一刻，矩形必须仍是【改动前】的那个矩形")
    from PySide6.QtWidgets import QApplication
    import core.data_manager as DM
    from ui.main_window import MainWindow
    from ui import metro_render as MR

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()
    mv = win.map_view

    seen = {"rect": None}
    _orig_pgc = MR.StationDotItem.prepareGeometryChange

    def spy_pgc(self):
        seen["rect"] = self.boundingRect()
        return _orig_pgc(self)
    MR.StationDotItem.prepareGeometryChange = spy_pgc

    def rect_of(it):
        r = it.boundingRect()
        return (round(r.x(), 3), round(r.y(), 3), round(r.width(), 3), round(r.height(), 3))

    def check_mutator(label: str, fn) -> None:
        bad = []
        for it in list(mv.station_items.values())[:40]:
            before = rect_of(it)
            seen["rect"] = None
            try:
                fn(it)
            except Exception as e:
                bad.append("%s 抛异常 %s" % (it.station_id, e))
                continue
            at = seen["rect"]
            if at is None:
                continue                       # 这个方法没声明几何变化（几何没变，正常）
            if (round(at.x(), 3), round(at.y(), 3),
                    round(at.width(), 3), round(at.height(), 3)) != before:
                bad.append("%s 声明时矩形≠改动前" % it.station_id)
        ok(label, not bad, ("；".join(bad[:3]) if bad else "40 个图元全部一致"))

    check_mutator("F1a set_label_side 顺序对", lambda it: it.set_label_side("left"))
    check_mutator("F1b apply_view_scale 顺序对", lambda it: it.apply_view_scale(0.5))
    check_mutator("F1c update_from_data 顺序对",
                  lambda it: it.update_from_data({"station_name": "测试站名ABC"}))
    check_mutator("F1d set_selected_visual 顺序对", lambda it: it.set_selected_visual(True))

    MR.StationDotItem.prepareGeometryChange = _orig_pgc

    # ---------------- F2：完整路径不崩 ----------------
    print("\nF2 组：改 379 个图元几何 → 全部删除 → 重绘（子进程跑，崩了就是 !=0）")
    code, tail = run_child(False)
    ok("F2 正常写法：子进程活着退出", code == 0, "returncode=%s %s" % (code, tail))

    # ---------------- F3：变异必须崩 ----------------
    print("\nF3 组：把 set_label_side 改回旧的错误顺序，子进程必须崩"
          "（证明这条回归抓得住）")
    code2, tail2 = run_child(True)
    ok("F3 错误写法：子进程确实崩了", code2 != 0, "returncode=%s %s" % (code2, tail2))

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    print("结论：%s" % ("全部通过 ✅" if FAIL == 0 else "有失败 ❌"))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
