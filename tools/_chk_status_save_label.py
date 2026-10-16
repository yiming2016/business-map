# -*- coding: utf-8 -*-
"""_chk_status_save_label.py —— 回归：状态栏「已保存: hh:mm:ss」必须是**真的**保存时刻。

修掉的坑（v2.5.5）：
    def _refresh_status(self):
        ...
        self.lbl_save.setText("已保存: " + time.strftime("%H:%M:%S"))   # ← 当前时间！
`_refresh_status()` 有 **7 处**调用，其中一处是**启动时**（载入完线路站点之后），
于是刚打开软件状态栏就显示"已保存: 04:41:41"——其实一次都没写盘。
任何一次状态刷新都会把它刷成"现在"，用户会以为数据刚落盘。
★ 这个假时间还会**把倒查数据异常的人带偏**（它不能当线索用）。

修法：真实落盘时刻记在 `self._last_save`（`_save_data()` 里写），
`_refresh_status()` 只负责显示它；本次会话还没存过就显示 `--`。

判据：
  A1 启动后（没保存过）        → "已保存: --"
  A2 反复刷新状态              → 仍然是 "--"（不许变成当前时间）
  A3 真的保存一次（拖动站点）  → 变成合法 hh:mm:ss 且与当前时间相差 < 120s
  A4 保存后再刷新状态          → 时刻**不变**（不许被刷成"现在"）
  A5 `_on_save_all()` 主动保存 → 时刻被更新

  --mutate-old-label：把 _refresh_status 换回"显示当前时间"的旧实现，
    用来证明本回归真的抓得住（此时 A1/A2 应当失败）。

运行：
    python tools/_chk_status_save_label.py
    python tools/_chk_status_save_label.py --mutate-old-label     # 应当失败
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

import core.data_manager as DM
from ui.main_window import MainWindow

PASS = FAIL = 0
HMS = "%H:%M:%S"


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


def _valid_hms(s: str) -> bool:
    try:
        time.strptime(s, HMS)
        return True
    except Exception:
        return False


def mutate_old_label() -> None:
    """把 _refresh_status 还原成"显示当前时间"的旧实现。"""
    import time as _t

    def old_refresh(self):
        self.lbl_count.setText("站点数: %d" % len(self.dm.all_stations()))
        self.lbl_save.setText("已保存: " + _t.strftime(HMS))
        self.lbl_zoom.setText("缩放: %d%%" % int(self.map_view._scale * 100))

    MainWindow._refresh_status = old_refresh


def text_of(win) -> str:
    return win.lbl_save.text()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-old-label", action="store_true")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="chk_label_"))
    DM.STATIONS_FILE = tmp / "stations.json"
    DM.LINES_FILE = tmp / "lines.json"

    if args.mutate_old_label:
        mutate_old_label()
        win._refresh_status()

    print("=" * 78)
    print("视口 %dx%d  站点 %d%s"
          % (win.map_view.viewport().width(), win.map_view.viewport().height(),
             len(win.map_view.station_items),
             "   【变异：_refresh_status 回到旧实现】" if args.mutate_old_label else ""))
    print("落盘目标已改到临时目录：%s" % tmp)

    # ---------- A1 启动后未保存 ----------
    print("\nA1 刚打开软件（本次会话还没保存过）")
    ok("A1 状态栏是「已保存: --」", text_of(win) == "已保存: --", repr(text_of(win)))

    # ---------- A2 反复刷新不许变成"现在" ----------
    print("\nA2 反复刷新状态（模拟任何一次 _refresh_status）")
    seen = set()
    for _ in range(3):
        win._refresh_status()
        app.processEvents()
        seen.add(text_of(win))
        time.sleep(1.1)          # 故意跨秒：旧实现会读出不同的时间
    ok("A2 刷新后仍然是「已保存: --」（没被刷成当前时间）",
       seen == {"已保存: --"}, "三次读到 %s" % sorted(seen))

    # ---------- A3 真保存一次 ----------
    print("\nA3 真的保存一次：拖动一个站点")
    sid, item = None, None
    for k, it in win.map_view.station_items.items():
        if it.scene() is not None:
            sid, item = k, it
            break
    before = text_of(win)
    p0 = item.pos()
    e_press = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMousePress)
    e_press.setButton(Qt.LeftButton); e_press.setScenePos(p0)
    item.mousePressEvent(e_press)
    item.setPos(QPointF(p0.x() + 20.0, p0.y()))
    ev_m = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseMove)
    ev_m.setButton(Qt.LeftButton); ev_m.setButtons(Qt.LeftButton)
    ev_m.setScenePos(item.pos()); ev_m.setLastScenePos(item.pos())
    item.mouseMoveEvent(ev_m)
    e_rel = QGraphicsSceneMouseEvent(QEvent.Type.GraphicsSceneMouseRelease)
    e_rel.setButton(Qt.LeftButton); e_rel.setScenePos(item.pos())
    item.mouseReleaseEvent(e_rel)
    app.processEvents()
    after = text_of(win)
    stamp = after.replace("已保存: ", "")
    ok("A3 保存后显示真实时刻（合法 hh:mm:ss）", _valid_hms(stamp), repr(after))
    now = time.strftime(HMS)

    def sec_of_day(s: str) -> int:
        h, m, sec = (int(x) for x in s.split(":"))
        return h * 3600 + m * 60 + sec

    # ★ 别用 time.mktime(time.strptime(s, "%H:%M:%S")) 比：Windows 上 strptime
    #   不带日期会得到 1900-01-01，mktime 直接抛 "argument out of range"。
    try:
        d = abs(sec_of_day(stamp) - sec_of_day(now))
        d = min(d, 86400 - d)          # 跨零点
    except Exception:
        d = 9e9
    ok("A3 该时刻与当前时间相差 < 120s（确实是刚写的）", d < 120.0,
       "%s vs now=%s 差 %.0fs" % (stamp, now, d))
    item.setPos(p0)
    app.processEvents()

    # ---------- A4 保存后再刷新，时刻不许变 ----------
    print("\nA4 保存之后继续刷新状态（不该再变）")
    t1 = text_of(win)
    time.sleep(1.2)
    win._refresh_status()
    app.processEvents()
    t2 = text_of(win)
    ok("A4 刷新不会把「已保存」刷成现在", t1 == t2,
       "%s → %s（改了就是又回到假时间）" % (t1, t2))

    # ---------- A5 主动保存 ----------
    print("\nA5 Ctrl+S 主动保存")
    time.sleep(1.2)
    win._on_save_all()
    app.processEvents()
    t3 = text_of(win)
    ok("A5 主动保存后时刻被更新", t3 != t2 and _valid_hms(t3.replace("已保存: ", "")),
       "%s → %s" % (t2, t3))

    print("\n" + "=" * 78)
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if args.mutate_old_label:
        print("（变异模式：这里**应该**看到 A1/A2 失败，才证明本回归真的抓得住）")
    elif FAIL == 0:
        print("全部通过 ✅")
    print("=" * 78)
    win.hide()


if __name__ == "__main__":
    main()
