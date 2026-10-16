# -*- coding: utf-8 -*-
"""v2.7.21 探针：⚙️ 弹窗两处微调。

用户原话：「'立即生成'按钮放到本行右侧；图片保存到的路径另起一行」
⇒ ① btn_now 从"每隔"行**最左**挪到**最右**；
   ② 「图片存到：」标签独占一小行，输入框 + 浏览…落到下一行。
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication                           # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                                # noqa: E402
from ui import image_mode as IM                                      # noqa: E402
from ui.image_settings_dialog import ImageSettingsDialog             # noqa: E402

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

bn = dlg._btn_now
lbp = dlg._lb_path


def _xy(w):
    """把控件左上角换算到**弹窗坐标系**（v2.7.24 起路径行包在 wrap 里，
    `geometry()` 是相对 wrap 的，直接比较会算错）。"""
    p = w.mapTo(dlg, w.rect().topLeft())
    return p.x(), p.y()


def _right(w):
    return _xy(w)[0] + w.width()


# ---- ① 「立即生成」在本行最右 ----
ok("① 按钮在「每隔」行右侧（cb_timer 右边）",
   _xy(bn)[0] > dlg.cb_timer.geometry().right() + 2,
   f"按钮左={_xy(bn)[0]} cb_timer右={dlg.cb_timer.geometry().right()}")
ok("①b 按钮贴在弹窗内容区右端（右边距 ≤ 40px）",
   0 < dlg.width() - _right(bn) <= 40,
   f"按钮右={_right(bn)} 弹窗宽={dlg.width()}")

# ---- ② 「图片存到」标签在上、输入框在下 ----
_lb_b = _xy(lbp)[1] + lbp.height()
_ed_t = _xy(dlg.ed_path)[1]
ok("② 标签在输入框**上方**（不与输入框同一行）",
   _lb_b <= _ed_t + 1, f"标签底={_lb_b} 输入框顶={_ed_t}")
ok("②b 标签左边缘与输入框左边缘对齐",
   abs(_xy(lbp)[0] - _xy(dlg.ed_path)[0]) <= 2,
   f"{_xy(lbp)[0]} vs {_xy(dlg.ed_path)[0]}")
# ★ v2.7.21b：用户「图片保存相关的你要左对齐啊」⇒ 这一项要**顶格**
# （跟「看图模式」区块第一个勾选项同一条竖线，不再缩进到字段列）
ok("②b2 标签/输入框顶格（与勾选项同左边缘）",
   abs(_xy(lbp)[0] - _xy(dlg.cb_auto)[0]) <= 4
   and abs(_xy(dlg.ed_path)[0] - _xy(dlg.cb_auto)[0]) <= 4,
   f"标签={_xy(lbp)[0]} 输入框={_xy(dlg.ed_path)[0]} "
   f"勾选项={_xy(dlg.cb_auto)[0]}")
ok("②c 输入框比 v2.7.20 更长（≥ 240px）",
   dlg.ed_path.width() >= 240, f"宽={dlg.ed_path.width()}")
# ★ v2.7.23：用户「你现在却把'浏览'按键加长了」⇒ 按钮必须按自身尺寸、不参与拉伸
bb = dlg._btn_browse
ok("②c2 浏览…按钮没被拉长（宽 ≤ 100）", bb.width() <= 100, f"宽={bb.width()}")
ok("②c3 浏览…按钮紧贴路径框右侧（间距 ≈ 6px）",
   abs(_xy(bb)[0] - _right(dlg.ed_path) - 6) <= 8,
   f"按钮左={_xy(bb)[0]} 路径框右={_right(dlg.ed_path)}")
ok("②c4 按钮右边缘贴弹窗内容右端（≤20px）",
   0 <= dlg.width() - _right(bb) <= 20,
   f"按钮右={_right(bb)} 弹窗宽={dlg.width()}")

# ---- ③ 弹窗最小宽度没被改大（离屏字体比真机宽，不拿绝对宽度做判据）----
ok("③ 最小宽度仍是 460（没为了塞内容改大）", dlg.minimumWidth() <= 460,
   f"min={dlg.minimumWidth()} 实际={dlg.width()}x{dlg.height()}")

# ---- ④ ★变异自检：把标签塞回输入框同一行 ⇒ ② 的判据必须失败 ----
g = dlg._grid2
g.removeWidget(lbp)
dlg._row_path.insertWidget(0, lbp)        # v2.7.24：路径行改成 wrap 内的横排
pump(8)
same_row = (_xy(lbp)[1] + lbp.height()) <= _xy(dlg.ed_path)[1] + 1
ok("④ ★变异自检：标签挪回同行 ⇒ '标签在上方'判据失效",
   not same_row, f"标签底={_xy(lbp)[1] + lbp.height()} 输入框顶={_xy(dlg.ed_path)[1]}")

# 复原（免得影响后面的截图/后续判据）
dlg._row_path.removeWidget(lbp)
g.insertWidget(1, lbp)                     # 竖排里：0=第一行wrap, 1=标签, 2=路径行wrap
pump(8)
ok("④b 复原后 ② 判据重新成立",
   (_xy(lbp)[1] + lbp.height()) <= _xy(dlg.ed_path)[1] + 1,
   f"标签底={_xy(lbp)[1] + lbp.height()} 输入框顶={_xy(dlg.ed_path)[1]}")

print("=" * 40)
print(f"结果：{N_OK} 过 / {len(FAILS)} 败")
for f in FAILS:
    print("  失败：", f)
sys.exit(1 if FAILS else 0)
