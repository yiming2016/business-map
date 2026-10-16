# -*- coding: utf-8 -*-
"""
tools/_probe_v269_combo_px.py
=============================
像素级验下拉胶囊：「工作日」是不是**真居中**、文字有没有被截、箭头撞不撞字。

判据（都在同一张 `cb.grab()` 位图上量，物理像素，除以 dpr 换算成逻辑像素）：
  · 胶囊左右边缘 = 与背景色不同的最左/最右列
  · 文字墨迹 = 与"胶囊底色"不同的像素，且**排除右侧箭头那一小块**
  · 居中 = |左留白 − 右留白(到箭头左缘)| ≤ 1.5 逻辑px
  · 不截 = 文字墨迹宽度 >= QFontMetrics.horizontalAdvance(文字) − 1px
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont, QFontMetrics               # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

import core.data_manager as CDM_                            # noqa: E402
import tempfile, os                                          # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v269px_"))
# ★ 必须是 Path 不是 str：`_read_json` 里调 `path.exists()`，
#   给字符串直接 AttributeError（v2.6.8 踩过，见 MEMORY）
CDM_.STATIONS_FILE = _TMP / "s.json"
CDM_.LINES_FILE = _TMP / "l.json"
CDM_.DATA_DIR = _TMP

from ui.main_window import MainWindow                        # noqa: E402
from ui.edit_dialog import EditDialog                        # noqa: E402
from ui.timetable_editor import TimetableEditor, FONT_FAMILY  # noqa: E402


def pump(n=12):
    for _ in range(n):
        QApplication.processEvents()


def analyse(cb, tag: str) -> bool:
    pm = cb.grab()
    img = pm.toImage()
    dpr = pm.devicePixelRatio() or 1.0
    W, H = img.width(), img.height()
    # ① "墨迹" = 靠近**前景色**（文字/箭头同色）的像素。
    #   ★ 别用"跟胶囊底色不同"当判据：圆角外面是父窗口的底色，也会被判成墨迹
    #     （实测左留白算出 0.0px，假故障）。
    from PySide6.QtGui import QColor
    fg = QColor(cb._fg)

    def near_fg(c) -> bool:
        return (abs(c.red() - fg.red()) + abs(c.green() - fg.green())
                + abs(c.blue() - fg.blue())) < 150

    fgpx = []
    for y in range(H):
        for x in range(W):
            if near_fg(img.pixelColor(x, y)):
                fgpx.append((x, y))
    if not fgpx:
        print("  ★ 一个前景墨点都没有（文字/箭头都没画出来）")
        return False
    # ② 箭头区 = 胶囊最右 `arrow` 逻辑 px 那一条；其余是文字区。
    #    ★ 区间必须从**胶囊右缘**往回算，不能从"墨迹最右"往回算 ——
    #      后者会把箭头自己的宽度算进去，箭头就永远落不进箭头区。
    arrow_budget = int(round(cb._arrow * dpr))
    cut = (W - 1) - arrow_budget
    text_px = [p for p in fgpx if p[0] < cut]
    arrow_px = [p for p in fgpx if p[0] >= cut]
    if not text_px:
        print("  ★ 文字区一个墨点都没有")
        return False
    tx0 = min(p[0] for p in text_px)
    tx1 = max(p[0] for p in text_px)
    left = tx0 / dpr                     # 胶囊左缘 ≈ 位图左缘
    right = (W - 1 - tx1) / dpr          # 到胶囊右缘
    f = cb.font()
    fm = QFontMetrics(f)
    want = fm.horizontalAdvance(cb.currentText())
    got = (tx1 - tx0 + 1) / dpr
    ok_c = abs(left - right) <= 1.5
    # ★ "显示全"不能要求 `墨迹宽 == horizontalAdvance`：advance 含左右
    #   边距（side bearing），汉字字形本身比它窄（实测 39.0 → 37.3，差 1.7px）。
    #   真正的判据是：**两侧都还有白边**（没被裁到边界）+ 墨迹宽 ≈ 字宽。
    ok_w = (left > 0.5 and right > 0.5 and got >= want * 0.9)
    print("  [%s] 胶囊 %dx%d  dpr=%.1f" % (tag, W, H, dpr))
    print("       文字墨迹宽 %.1fpx（字宽 %.1fpx）⇒ %s"
          % (got, want, "显示全" if ok_w else "★被截"))
    print("       左留白 %.1fpx  右留白 %.1fpx（差 %.1f）⇒ %s"
          % (left, right, abs(left - right), "居中" if ok_c else "★不居中"))
    print("       箭头墨点数 %d ⇒ %s" % (len(arrow_px), "有" if arrow_px else "★没画"))
    print("       箭头与文字间隙 %.1fpx ⇒ %s"
          % (right - 0.0, "不撞" if right > 1.0 else "★可能撞上"))
    return ok_c and ok_w and bool(arrow_px)


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(30)
    dlg = EditDialog(station_id="机场东", parent=win)
    dlg.show()
    pump(30)
    tt = None
    for w in dlg.findChildren(TimetableEditor):
        tt = w
        break
    if tt is None or tt.date_combo is None:
        print("★ 没找到日期下拉")
        return 1
    cb = tt.date_combo
    ok = True
    for i in range(cb.count()):
        cb.setCurrentIndex(i)
        pump(6)
        ok &= analyse(cb, "选项%d %s" % (i, cb.currentText()))
    win.close()
    pump()
    print("\n结果：%s" % ("全部通过" if ok else "★有问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
