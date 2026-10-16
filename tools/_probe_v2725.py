# -*- coding: utf-8 -*-
"""v2.7.25 探针：两条勾选项并排一行（文案缩短）。

用户原话：「把『启动软件后自动生成一次、直接进看图模式』放到『切到看图模式时
自动生成图片』右侧」。两条完整文字真机约 600px、可用宽 438px 放不下 ⇒
经点选确认走"缩短两条文字"，原话移入悬停提示。
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication                              # noqa: E402
from PySide6.QtTest import QTest                                        # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                                   # noqa: E402
from ui import image_mode as IM                                         # noqa: E402
from ui.image_settings_dialog import ImageSettingsDialog                # noqa: E402

FAILS = []
N_OK = 0


def ok(name, cond, info=""):
    global N_OK
    if cond:
        N_OK += 1
        print(f"  [OK] {name}" + (f"  —— {info}" if info else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  —— {info}" if info else ""))


def pump(n=10):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(20)
d = win._data_dir()

dlg = ImageSettingsDialog(win, IM.load_settings(d), d)
dlg.show()
pump(12)


def _xy(w):
    p = w.mapTo(dlg, w.rect().topLeft())
    return p.x(), p.y()


ca, cs = dlg.cb_auto, dlg.cb_start

# ---- ① 两条同一行，且 start 在 auto 右侧 ----
ok("① 两条勾选项**同一行**（top 相同）",
   abs(_xy(ca)[1] - _xy(cs)[1]) <= 2, f"top {_xy(ca)[1]} vs {_xy(cs)[1]}")
ok("①b 「启动时…」在「看图模式…」右侧",
   _xy(cs)[0] >= _xy(ca)[0] + ca.width(), f"start左={_xy(cs)[0]} auto右={_xy(ca)[0] + ca.width()}")
ok("①c 两条之间间距被压缩（≤40px）",
   0 < _xy(cs)[0] - (_xy(ca)[0] + ca.width()) <= 40,
   f"gap={_xy(cs)[0] - (_xy(ca)[0] + ca.width())}")

# ---- ② 文案已缩短（原话进了 tooltip）----
ok("② 两条文案都缩短了（≤12 字）",
   len(ca.text()) <= 12 and len(cs.text()) <= 12,
   f"「{ca.text()}」({len(ca.text())}字) / 「{cs.text()}」({len(cs.text())}字)")
ok("②b 悬停提示里保留原话",
   "切到看图模式时自动生成图片" in ca.toolTip()
   and "启动软件后自动生成一次" in cs.toolTip(),
   "tooltip 已含原句")

# ---- ③ 两条勾选项仍顶格（与「图片存到：」同左边缘）----
ok("③ 左勾选项仍顶格", abs(_xy(ca)[0] - _xy(dlg._lb_path)[0]) <= 6,
   f"勾选项={_xy(ca)[0]} 图片存到={_xy(dlg._lb_path)[0]}")

# ---- ④ 整行没顶出弹窗（真机估算 366px 内）----
ok("④ 第二条勾选框右边缘在弹窗内",
   _xy(cs)[0] + cs.width() <= dlg.width() - 11,
   f"start右={_xy(cs)[0] + cs.width()} 弹窗宽={dlg.width()}")

# ---- ⑤ 弹窗最小宽度没被改大 ----
ok("⑤ 最小宽度仍是 460", dlg.minimumWidth() <= 460,
   f"min={dlg.minimumWidth()} 实际={dlg.width()}x{dlg.height()}")

# ---- ⑥ 旧的「每隔 + 立即生成」行没被弄坏 ----
ok("⑥ 「立即生成」仍在「每隔」行右侧",
   _xy(dlg._btn_now)[0] > _xy(dlg.cb_timer)[0] + dlg.cb_timer.width(),
   f"按钮左={_xy(dlg._btn_now)[0]} 每隔右={_xy(dlg.cb_timer)[0] + dlg.cb_timer.width()}")

# ---- ⑦ ★变异自检：把 start 挪回下一行 ⇒ ① 判据必须失败 ----
rt = dlg._row_top
rt.removeWidget(cs)
dlg._grid.addWidget(cs)
pump(10)
same_row = abs(_xy(ca)[1] - _xy(cs)[1]) <= 2
ok("⑦ ★变异自检：挪回下一行 ⇒ '同一行'判据失效", not same_row,
   f"top {_xy(ca)[1]} vs {_xy(cs)[1]}")

# 复原（插回 20px 弹簧之前：0=auto, 1=spacing, 2=start, 3=stretch）
dlg._grid.removeWidget(cs)
rt.insertWidget(2, cs)
pump(10)
ok("⑦b 复原后 ① 判据重新成立",
   abs(_xy(ca)[1] - _xy(cs)[1]) <= 2, f"top {_xy(ca)[1]} vs {_xy(cs)[1]}")

print("=" * 40)
print(f"v2.7.25 探针：{N_OK} 通过 / {len(FAILS)} 失败")
for f in FAILS:
    print("  失败：", f)
sys.exit(1 if FAILS else 0)
