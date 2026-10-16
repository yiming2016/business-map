# -*- coding: utf-8 -*-
"""v2.7.10 探针：选中的站点**变红并保持**（圆点填充 + 站名都红，取消才恢复）。

★ 全程离屏（QT_QPA_PLATFORM=offscreen），不弹任何窗口。
★ 用户原话：「选中的站点变为红色，即变红加闪烁，只要没有取消选择则保持红色」
  ⇒ 判据：① 选中后圆点真的是红的（渲染取样，不是只看标志位）；
          ② 站名笔刷是红的；③ 闪烁结束后**仍然红**；
          ④ 取消选中后圆点和站名**都回到原样**。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtGui import QColor, QImage, QPainter     # noqa: E402
from PySide6.QtCore import QRectF, Qt                  # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtTest import QTest                       # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"   （{extra}）" if extra else ""))


app = QApplication(sys.argv)
from ui.main_window import MainWindow       # noqa: E402
from ui.metro_render import (StationDotItem, SELECTED_FILL,  # noqa: E402
                             LABEL_COLOR_NORMAL)

win = MainWindow()
win.show()


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


pump(12)
mv = win.map_view

# 找一个普通站、一个换乘站
plain = tr = None
for sid, it in mv.station_items.items():
    if plain is None and not it.is_transfer:
        plain = sid
    if tr is None and it.is_transfer:
        tr = sid
    if plain and tr:
        break
print(f"     （普通站 {plain} / 换乘站 {tr}）")


def dot_pixel(sid):
    """在站点圆心处渲染取样一个像素（离屏也成立）。"""
    it = mv.station_items[sid]
    half = 26.0 / max(mv.transform().m11(), 1e-6)
    p = it.scenePos()
    src = QRectF(p.x() - half, p.y() - half, half * 2, half * 2)
    img = QImage(60, 60, QImage.Format_ARGB32)
    img.fill(Qt.white)
    pt = QPainter(img)
    mv.scene_.render(pt, QRectF(0, 0, 60, 60), src)
    pt.end()
    return QColor(img.pixel(30, 30))


def is_red(c: QColor) -> bool:
    return c.red() > 140 and c.green() < 90 and c.blue() < 90


def label_red(sid) -> bool:
    it = mv.station_items[sid]
    return it.label.brush().color().name().lower() == SELECTED_FILL.lower()


def label_normal(sid) -> bool:
    """★ v2.7.11：选中时站名**不再变红**（用户要求"文字不闪烁"，文字也不变色）。"""
    it = mv.station_items[sid]
    return it.label.brush().color().name().lower() == LABEL_COLOR_NORMAL.lower()


print("\n===== A 选中 ⇒ 变红 =====")
mv.select_station(plain, reveal=False)
pump()
it = mv.station_items[plain]
ok("A1 选中标志置位", it._selected is True)
c = dot_pixel(plain)
ok("A2 圆点**填充成红色**（渲染取样圆心）", is_red(c),
   f"圆心像素 {c.name()}  R{c.red()} G{c.green()} B{c.blue()}")
ok("A3 站名保持原字色（v2.7.11 起文字不变色）", label_normal(plain))

print("\n===== B 换乘站（白心药丸）也整个填红 =====")
mv.select_station(tr, reveal=False)
pump()
ct = dot_pixel(tr)
ok("B1 换乘站圆心也红（不再是白心 / 线路色）", is_red(ct),
   f"圆心像素 {ct.name()}")
ok("B2 换乘站站名也保持原字色", label_normal(tr))
ok("B3 上一个站已恢复（只剩一个红站）",
   mv.station_items[plain]._selected is False
   and not label_red(plain) and label_normal(plain))

print("\n===== C 闪烁结束后**仍然红**（不取消就不褪色）=====")
mv.select_station(plain, reveal=False)
# 等闪烁定时器自己跑完（4 个来回 × 280ms ≈ 2.5s，这里给足 4s）
for _ in range(80):
    app.processEvents()
    QTest.qWait(50)
ok("C1 闪烁已结束", mv._blink_timer is None or not mv._blink_timer.isActive())
ok("C2 闪烁结束后圆点**还是红的**", is_red(dot_pixel(plain)),
   f"圆心像素 {dot_pixel(plain).name()}")
ok("C3 站名不受闪烁影响（字色/透明度都不动）", label_normal(plain))

print("\n===== D 取消选中 ⇒ 恢复原样 =====")
mv.clear_selection()
pump()
ok("D1 选中标志清掉", mv.station_items[plain]._selected is False)
c2 = dot_pixel(plain)
ok("D2 圆点恢复（不再是红的）", not is_red(c2), f"圆心像素 {c2.name()}")
ok("D3 站名恢复原字色", label_normal(plain))

print("\n===== E 变异自检：把填充色改成白色 ⇒ A2 必须变红 =====")
import ui.metro_render as MRX                       # noqa: E402
_orig_fill = MRX.SELECTED_FILL
MRX.SELECTED_FILL = "#ffffff"
try:
    mv.select_station(plain, reveal=False)
    pump()
    c = dot_pixel(plain)
    ok("E1 白填充时圆心不再是红 ⇒ 判据在岗", not is_red(c), f"圆心 {c.name()}")
finally:
    MRX.SELECTED_FILL = _orig_fill
mv.select_station(plain, reveal=False)
pump()
ok("E2 装回后恢复红色", is_red(dot_pixel(plain)))
mv.clear_selection()


print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项：" + "、".join(FAIL))
win.close()
sys.exit(1 if FAIL else 0)
