# -*- coding: utf-8 -*-
"""v2.7.24 探针：「拖动留白」并到「右侧面板宽度」同一行右侧，并压缩间距。

用户原话（附两张裁剪截图）：「把『拖动留白：60px』挪到『右侧面板宽度：500px』
右侧同一行，适当压缩间距」。
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication, QLabel                    # noqa: E402
from PySide6.QtTest import QTest                                      # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                                 # noqa: E402
from ui import image_mode as IM                                       # noqa: E402
from ui.image_settings_dialog import ImageSettingsDialog              # noqa: E402

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

labs = {w.text(): w for w in dlg.findChildren(QLabel)}
lb_pan = labs["右侧面板宽度："]
lb_pad = labs.get("拖动余量：") or labs["拖动留白："]   # v2.7.29 改名（旧名兼容）

# ---- ① 两个数字框在同一行 ----
ok("① 两个数字框**同一行**（top 相同）",
   abs(dlg.sp_info_w.geometry().top() - dlg.sp_pan_pad.geometry().top()) <= 2,
   f"top {dlg.sp_info_w.geometry().top()} vs {dlg.sp_pan_pad.geometry().top()}")
ok("①b 「拖动留白」标签也在这行（top 相同）",
   abs(lb_pad.geometry().top() - lb_pan.geometry().top()) <= 3,
   f"top {lb_pad.geometry().top()} vs {lb_pan.geometry().top()}")

# ---- ② 拖动留白在右侧面板字段的右边 ----
ok("② 「拖动留白」那一组在右半侧",
   dlg.sp_pan_pad.geometry().left() > dlg.sp_info_w.geometry().right() + 8,
   f"留白框左={dlg.sp_pan_pad.geometry().left()} 宽度框右={dlg.sp_info_w.geometry().right()}")

# ---- ③ 间距被压缩（两组之间 ≤ 40px）----
# ★ v2.7.26：数字框的「px」单位从框内移到框外 ⇒ 间距要从**单位标签右边缘**量起
#   （否则会把那枚 px 标签的宽度算进"间距"里，得出虚高的 51px）
_px = getattr(dlg, "_lb_px_info", None)
_anchor = _px.geometry().right() if _px is not None \
    else dlg.sp_info_w.geometry().right()
gap = lb_pad.geometry().left() - _anchor
ok("③ 两组之间间距被压缩（≤40px）", 0 < gap <= 40, f"gap={gap}")

# ---- ④ 数字框变短（132 → 104）----
ok("④ 数字框宽度收短（≤110）", dlg.sp_info_w.width() <= 110,
   f"宽={dlg.sp_info_w.width()}")

# ---- ⑤ 整行没撑出弹窗内容区 ----
ok("⑤ 留白框没顶出右边界", dlg.sp_pan_pad.geometry().right() <= dlg.width() - 11,
   f"留白框右={dlg.sp_pan_pad.geometry().right()} 弹窗宽={dlg.width()}")

# ---- ⑥ 路径那两行没被这轮改动弄坏 ----
def _gx(w):
    return w.mapTo(dlg, w.rect().topLeft()).x()


ok("⑥ 路径标签仍顶格 + 输入框仍顶格",
   abs(_gx(dlg._lb_path) - _gx(dlg.cb_auto)) <= 4
   and abs(_gx(dlg.ed_path) - _gx(dlg.cb_auto)) <= 4,
   f"标签={_gx(dlg._lb_path)} 输入框={_gx(dlg.ed_path)} "
   f"勾选项={_gx(dlg.cb_auto)}")
ok("⑥b 浏览…按钮仍是小尺寸", dlg._btn_browse.width() <= 100,
   f"宽={dlg._btn_browse.width()}")

# ---- ⑦ ★变异自检：把「拖动留白」那组挪回下一行 ⇒ ① 判据必须失败 ----
# 直接把 sp_pan_pad / 标签从当前行里摘掉、塞回主竖排布局末尾（模拟"另起一行"）
inner = dlg.sp_pan_pad.parentWidget().layout()
inner.removeWidget(dlg.sp_pan_pad)
inner.removeWidget(lb_pad)
dlg._grid2.addWidget(lb_pad)
dlg._grid2.addWidget(dlg.sp_pan_pad)
pump(10)
same_row = abs(dlg.sp_info_w.geometry().top() -
               dlg.sp_pan_pad.geometry().top()) <= 2
ok("⑦ ★变异自检：另起一行 ⇒ '同一行'判据失效", not same_row,
   f"top {dlg.sp_info_w.geometry().top()} vs {dlg.sp_pan_pad.geometry().top()}")

# 复原（插回 20px 弹簧之后）
dlg._grid2.removeWidget(lb_pad)
dlg._grid2.removeWidget(dlg.sp_pan_pad)
inner.insertWidget(3, lb_pad)
inner.insertWidget(4, dlg.sp_pan_pad)
pump(10)
ok("⑦b 复原后 ① 判据重新成立",
   abs(dlg.sp_info_w.geometry().top() - dlg.sp_pan_pad.geometry().top()) <= 2,
   f"top {dlg.sp_info_w.geometry().top()} vs {dlg.sp_pan_pad.geometry().top()}")

print("=" * 40)
print(f"v2.7.24 探针：{N_OK} 通过 / {len(FAILS)} 失败")
for f in FAILS:
    print("  失败：", f)
sys.exit(1 if FAILS else 0)
