"""
tools/test_interaction.py
================================
交互回归测试：空白处拖动平移 / 空白单击取消选择 / 双击空白新增 / 拖动站点。

全部用合成鼠标事件直接调用事件处理函数，不弹任何窗口。
"""

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication                       # noqa: E402
from PySide6.QtCore import QTimer, QPointF, QPoint, QEvent       # noqa: E402
from PySide6.QtGui import QFont, QMouseEvent                     # noqa: E402


def mk_event(kind, local: QPoint, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        kind, QPointF(local), QPointF(local),
        button, buttons, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.NoModifier,
    )


def main():
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)

    from ui.main_window import MainWindow
    from PySide6.QtCore import Qt
    w = MainWindow()
    w.resize(1600, 950)
    w.show()

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))
        print(("  [PASS] " if ok else "  [FAIL] ") + name + ("  " + detail if detail else ""))

    def run():
        mv = w.map_view

        # ★ 关键：先断开主窗口那两个"会弹出模态对话框"的槽，
        #   否则测试会卡在 dlg.exec() 上。
        for sig in (mv.add_station_requested, mv.station_double_clicked):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

        # 先放大到 50%，让内容大于视口 —— 否则"适配窗口"下滚动条没有可滚范围，
        # 平移测试会误判成失败。
        mv.fit_map()
        mv.resetTransform()
        mv.scale(0.5, 0.5)
        mv._scale = 0.5
        mv._apply_line_width()
        mv._apply_station_scale_all()
        mv.centerOn(mv.scene_.sceneRect().center())
        app.processEvents()

        # 找一个"空白"视口坐标：从右下角往左上扫
        empty = None
        vp = mv.viewport().rect()
        for y in range(vp.bottom() - 8, vp.top(), -17):
            for x in range(vp.right() - 8, vp.left(), -17):
                if mv.station_at(mv.mapToScene(QPoint(x, y))) is None:
                    empty = QPoint(x, y)
                    break
            if empty:
                break
        check("找到空白视口坐标", empty is not None, str(empty) if empty else "")
        if empty is None:
            app.quit()
            return

        # --- 1) 空白处拖动 → 平移 ---
        h0 = mv.horizontalScrollBar().value()
        v0 = mv.verticalScrollBar().value()
        mv.mousePressEvent(mk_event(QEvent.MouseButtonPress, empty, Qt.LeftButton, Qt.LeftButton))
        check("空白按下后进入平移状态", mv._panning is True)
        for step in range(1, 6):
            p = QPoint(empty.x() - step * 12, empty.y() - step * 8)
            mv.mouseMoveEvent(mk_event(QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton))
        mv.mouseReleaseEvent(mk_event(QEvent.MouseButtonRelease,
                                      QPoint(empty.x() - 60, empty.y() - 40),
                                      Qt.LeftButton, Qt.NoButton))
        h1 = mv.horizontalScrollBar().value()
        v1 = mv.verticalScrollBar().value()
        check("拖动后视图发生平移", (h1 != h0 or v1 != v0),
              f"h {h0}->{h1}, v {v0}->{v1}")
        check("平移结束后退出平移状态", mv._panning is False)
        check("拖动后屏蔽了紧随的双击", mv._suppress_dblclick is True)

        # --- 2) 拖动后的双击被忽略（不该弹新增窗口） ---
        added = []
        mv.add_station_requested.connect(lambda p: added.append(p))
        mv.mouseDoubleClickEvent(mk_event(QEvent.MouseButtonDblClick, empty,
                                          Qt.LeftButton, Qt.LeftButton))
        check("拖动后的双击不会误触发新建站点", len(added) == 0)

        # --- 3) 空白单击（不拖动）→ 取消选择 ---
        if mv.station_items:
            sid = list(mv.station_items)[0]
            mv.select_station(sid)
            is_sel = mv.station_items[sid]._selected
        else:
            is_sel = False
        mv.mousePressEvent(mk_event(QEvent.MouseButtonPress, empty, Qt.LeftButton, Qt.LeftButton))
        mv.mouseReleaseEvent(mk_event(QEvent.MouseButtonRelease, empty,
                                      Qt.LeftButton, Qt.NoButton))
        check("选中态点空白后取消选择",
              (not is_sel) or (mv._focus_station_id == "" and not any(
                  it._selected for it in mv.station_items.values())))
        check("空白单击不会误触发新建站点", len(added) == 0)

        # --- 4) 双击空白 → 仍然新增 ---
        mv.mouseDoubleClickEvent(mk_event(QEvent.MouseButtonDblClick, empty,
                                         Qt.LeftButton, Qt.LeftButton))
        check("双击空白仍能新建站点", len(added) == 1)

        # --- 5) 中键拖动 → 平移 ---
        h0 = mv.horizontalScrollBar().value()
        mv.mousePressEvent(mk_event(QEvent.MouseButtonPress, empty, Qt.MiddleButton, Qt.MiddleButton))
        check("中键按下进入平移状态", mv._panning is True)
        mv.mouseMoveEvent(mk_event(QEvent.MouseMove, QPoint(empty.x() - 40, empty.y()),
                                   Qt.NoButton, Qt.MiddleButton))
        mv.mouseReleaseEvent(mk_event(QEvent.MouseButtonRelease, QPoint(empty.x() - 40, empty.y()),
                                      Qt.MiddleButton, Qt.NoButton))
        check("中键拖动可平移", mv.horizontalScrollBar().value() != h0)
        check("中键平移不会取消选择逻辑", mv._panning is False)

        # --- 6) 按在站点上拖动 → 移动站点，而不是平移地图 ---
        sid = list(mv.station_items)[0]
        it = mv.station_items[sid]
        sp = mv.mapFromScene(it.pos())
        h0 = mv.horizontalScrollBar().value()
        mv.mousePressEvent(mk_event(QEvent.MouseButtonPress, sp, Qt.LeftButton, Qt.LeftButton))
        check("按在站点上不进入平移", mv._panning is False)
        check("按在站点上能正确命中站点", mv.station_at(mv.mapToScene(sp)) is not None)

        print()
        bad = [r for r in results if not r[1]]
        print(f"共 {len(results)} 项，失败 {len(bad)} 项")
        app.quit()

    QTimer.singleShot(1200, run)
    app.exec()


if __name__ == "__main__":
    main()
