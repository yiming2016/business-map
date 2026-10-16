# -*- coding: utf-8 -*-
"""v2.7.9 探针：出入口「详细信息框」高度 = **不满 2 行占 2 行，超过 2 行有多少显示多少**。

★ 全程离屏（QT_QPA_PLATFORM=offscreen），屏幕上不会弹出任何窗口。
★ 别和 `tools/_probe_v279.py` 弄混 —— 那个是 **v2.6.79** 的老探针。

背景（用户原话 v2.7.9，附截图）：「你自己看都多少行了，不满 2 行占用两行；
超过两行不再干预」⇒ 用户澄清「不再干预的意思是有多少显示多少」。
真因：行高只在构造 / 加行时算过一次，那时布局还没定型（视口只有几十像素宽），
      于是每个框都被算成 5 行（实测 70px）；宽度稳定后**再没人重算**。
      ⇒ 本轮给 ExitsEditor 挂了 `resizeEvent` 重算。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout   # noqa: E402
from PySide6.QtGui import QFontMetrics                             # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f"   （{extra}）" if extra else ""))


app = QApplication(sys.argv)
from ui.main_window import MainWindow                    # noqa: E402
from ui.exits_editor import ExitsEditor                  # noqa: E402
from ui.autofit import doc_height, min_height_for_lines  # noqa: E402

win = MainWindow()
win.show()


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


pump(12)
mv = win.map_view

print("===== A 右侧面板：真实站点 =====")
mv.select_station("机场东", reveal=False)
pump()
eds = win.info_panel.findChildren(ExitsEditor)
ok("A0 面板里真的有出入口编辑器", len(eds) == 1, f"{len(eds)} 个")
ee = eds[0]

base2 = min_height_for_lines(ee.rows[0][1], 2)
ls = QFontMetrics(ee.rows[0][1].font()).lineSpacing()
print(f"     （2 行基准 = {base2}px，行距 {ls}px，共 {len(ee.rows)} 行）")

short = [r[1] for r in ee.rows]
hs = [t.height() for t in short]
# ★ "不满 2 行"指的是**文字只有一行**的那些行；文字本身就要 2 行的（机场东 D）
#   高度自然会比 2 行基准多几个像素（边框 + FRAME_PAD），那不算违规。
one_line = [t for t in short if doc_height(t) <= base2 - ls]
ok("A1 文字只占 1 行的框 = 2 行高（不满 2 行也占 2 行）",
   all(abs(t.height() - base2) <= 2 for t in one_line),
   f"{len(one_line)} 个单行框，高 {[t.height() for t in one_line]}")

ok("A2 没有框被撑成 3 行以上（旧毛病：一律 70px）",
   max(hs) < base2 + 2 * ls, f"最高 {max(hs)}px，2 行={base2}px")

ok("A3 文字都装得下（不出现内部滚动条）",
   all(doc_height(t) <= t.viewport().height() + 1 for t in short))

print("\n===== B 超过 2 行 ⇒ 有多少显示多少（不封顶）=====")
host = QWidget()
lay = QVBoxLayout(host)
lay.setContentsMargins(0, 0, 0, 0)
cases = [("短", "A出入口：宝安大道"),
         ("超长", "A出入口：" + "宝安大道西侧、福围儿童公园、宝安海事局、" * 6)]
for _nm, val in cases:
    lay.addWidget(ExitsEditor(val))
host.resize(464, 900)
host.show()
pump()
boxes = host.findChildren(ExitsEditor)
h_short = boxes[0].rows[0][1].height()
t_long = boxes[1].rows[0][1]
dh_long = doc_height(t_long)
ok("B1 超长内容的框**比 2 行高**（真的跟着内容长）",
   t_long.height() > h_short + ls, f"短 {h_short}px → 超长 {t_long.height()}px")
ok("B2 超长内容**全部显示**（没有内部滚动、没有截断）",
   dh_long <= t_long.viewport().height() + 1,
   f"文字 {dh_long:.0f}px / 视口 {t_long.viewport().height()}px")

print("\n===== C 变异自检：拆掉 resizeEvent ⇒ A1/A2 必须变红 =====")
_orig_resize = ExitsEditor.resizeEvent
ExitsEditor.resizeEvent = lambda self, ev: QWidget.resizeEvent(self, ev)
try:
    mv.select_station("固戍", reveal=False)
    pump()
    eds2 = win.info_panel.findChildren(ExitsEditor)
    bad = [r[1].height() for r in eds2[0].rows] if eds2 else [0]
    b2 = min_height_for_lines(eds2[0].rows[0][1], 2) if eds2 else 0
    ok("C1 拆掉重算后高度不再等于 2 行 ⇒ 判据在岗",
       not all(abs(h - b2) <= 2 for h in bad),
       f"旧行为各框高 {bad}（2 行={b2}px）")
finally:
    ExitsEditor.resizeEvent = _orig_resize

mv.select_station("固戍", reveal=False)
pump()
eds3 = win.info_panel.findChildren(ExitsEditor)
good = [r[1].height() for r in eds3[0].rows]
g2 = min_height_for_lines(eds3[0].rows[0][1], 2)
ok("C2 装回重算后恢复正常", all(abs(h - g2) <= 2 for h in good), f"{good}")

print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项：" + "、".join(FAIL))
win.close()
sys.exit(1 if FAIL else 0)
