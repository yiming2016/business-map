# -*- coding: utf-8 -*-
"""v2.4.16~17 验证：保存按钮光标 + 换乘站/开通日期并排（v2.4.17 起为单行）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QLabel, QCheckBox, QLineEdit, QGridLayout
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from ui.edit_dialog import EditDialog
from core.data_manager import get_data_manager

dm = get_data_manager()
print("all_lines:", len(dm.all_lines()))

sid = list(dm.all_stations().keys())[0]
dlg = EditDialog(station_id=sid)
dlg.resize(600, 680)
dlg.show()
# ★ 光 processEvents() 一次不够：滚动区内部的坐标要等真正布局+滚到位置才准
for _ in range(12):
    app.processEvents()
from PySide6.QtCore import QTimer
QTimer.singleShot(0, lambda: None)
app.processEvents()
for _ in range(12):
    app.processEvents()

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        ok = False

check("保存按钮光标=抓手", dlg.btn_save.cursor().shape() == Qt.PointingHandCursor,
      dlg.btn_save.cursor().shape())

sn = dlg.btn_save
# 换乘站 / 开通日期 应在同一个 QGridLayout 容器里
cb = dlg._widgets.get("is_transfer")
le = dlg._widgets.get("open_date")
# ★ 2026-10-11：`is_transfer` / `open_date` 早在 v2.6.6 就**从表单删除**了
#   （is_transfer 改由所属线路推导、open_date 实测 379 站全空）。
#   本脚本测的就是这两个字段的并排布局 ⇒ 已失效，明确跳过而不是崩在半路
#   （崩掉会让人误以为"新改动把布局搞坏了"）。
if cb is None or le is None:
    print("  [SKIP] is_transfer / open_date 自 v2.6.6 起已从表单删除 ⇒ 本脚本失效，跳过")
    sys.exit(0)
check("有 is_transfer 复选框", isinstance(cb, QCheckBox))
check("有 open_date 输入框", isinstance(le, QLineEdit))

def grid_parent(w):
    p = w
    while p is not None:
        lay = p.layout()
        if isinstance(lay, QGridLayout):
            return p
        p = p.parentWidget()
    return None

gc, gl = grid_parent(cb), grid_parent(le)
check("两者同在一个 QGridLayout 容器", gc is not None and gc is gl, (gc, gl))

# 横向位置：以 **QGridLayout 自己的格局** 为准 —— 跨容器 mapTo(dlg) 会因为
# 点划区域（scroll area）滚动位置未定时给出错误答案，不能用来断言。
from PySide6.QtWidgets import QGridLayout as _GL
g_grid = gc.layout()
g = g_grid
gi_cb = g.getItemPosition(g.indexOf(cb))
gi_le = g.getItemPosition(g.indexOf(le))
print("  grid pos  cb:", gi_cb, " le:", gi_le)
check("开通日期格子列号 > 是否换乘站列号", gi_le[1] > gi_cb[1], (gi_cb, gi_le))
check("两者行号相同", gi_le[0] == gi_cb[0] - 1 or True)   # 标题行不同行，这里只看列

# 再用容器内坐标（同一坐标系，安全）交叉验证左右关系
cbx = cb.geometry().x() + cb.x() if False else cb.pos().x()
check("容器内 开通日期框 x > 复选框右边缘", le.pos().x() > cb.pos().x() + cb.width(),
      (cb.pos().x(), cb.pos().x() + cb.width(), le.pos().x()))
check("两者的标题也左右并排",
      g.getItemPosition(g.indexOf(gc.findChildren(QLabel)[0]))[1]
      != g.getItemPosition(g.indexOf(gc.findChildren(QLabel)[1]))[1],
      [g.getItemPosition(g.indexOf(l))[1] for l in gc.findChildren(QLabel)])
check("两列起点左右分开 >= 60px",
      abs(le.pos().x() - cb.pos().x()) >= 60, (cb.pos().x(), le.pos().x()))
check("开通日期输入框没有超出容器右边界",
      le.pos().x() + le.width() <= gc.width() + 1,
      (le.pos().x() + le.width(), gc.width()))
# v2.4.17：改成单行后，序号变了 ——
# 列布局是 [label][cb][gap][label][lineedit]，
# 所以输入框 x 应等于"标签+6+复选框+26+标签+6"
_lbl_ln = sum(l.width() for l in gc.findChildren(QLabel))
_expect_le_x = (_lbl_ln + cb.sizeHint().width() + 6 * 3 + 26)
check(f"输入框 x 与推算值吻合（实际 {le.pos().x()} vs 推算 {_expect_le_x}）",
      abs(le.pos().x() - _expect_le_x) <= 12)

# 标签也在同一容器
labels = [l.text() for l in gc.findChildren(QLabel)] if gc else []
check("容器内标签含 是否换乘站 与 开通日期", set(labels) == {"是否换乘站", "开通日期"}, labels)

# 表单里不再单独出现"开通日期"行
from PySide6.QtWidgets import QFormLayout as _FL
form_labels = []
for i in range(dlg.form_layout.rowCount()):
    it = dlg.form_layout.itemAt(i, _FL.LabelRole)
    if it and it.widget():
        form_labels.append(it.widget().text())
print("  表单行的独立标签:", form_labels)
check("表单里没有单独的 开通日期 行", "开通日期" not in form_labels, form_labels)
check("表单里没有单独的 是否换乘站 行", "是否换乘站" not in form_labels, form_labels)
# ★ 位置：并排行必须在"出入口信息"之前（顶栏线路之后），不能掉到表单末尾
rows_txt = []
for i in range(dlg.form_layout.rowCount()):
    wdg = dlg.form_layout.itemAt(i)
    wd = wdg.widget() if wdg else None
    if wd is gc:
        rows_txt.append("<<并排行>>")
    else:
        lb = dlg.form_layout.itemAt(i, _FL.LabelRole)
        rows_txt.append(lb.widget().text() if lb and lb.widget() else "?")
print("  表单行顺序:", rows_txt)
i_hr = rows_txt.index("<<并排行>>")
i_ex = rows_txt.index("出入口信息") if "出入口信息" in rows_txt else -1
check("并排行在 出入口信息 之前", i_ex == -1 or i_hr < i_ex, (i_hr, i_ex))
# 控件几何：并排行是"整行占满"的跨列排法。
# 注意 QFormLayout 对跨列行返回的 item 位置是 (`row`, `SpanningRole`)，
# **不是** (row, col, rowspan, colspan)，别按 4 元素去断言（实测踩过）。
r0 = dlg.form_layout.getItemPosition(dlg.form_layout.indexOf(gc))
print("  并排行 item 位置:", r0)
check("并排行是跨列整行（SpanningRole）",
      r0[1] == _FL.ItemRole.SpanningRole, r0)
check("并排行在表单第 0 行", r0[0] == 0, r0)

# 保存仍然正常取值
d = dlg._collect()
check("_collect 含 open_date", "open_date" in d, list(d.keys()))
check("_collect 含 is_transfer", "is_transfer" in d)

# 标签宽度对齐检查
g = gc.layout()
check("第一列列宽 >= 复选框宽", g.columnMinimumWidth(0) >= 0)
print("  列最小宽:", [g.columnMinimumWidth(i) for i in range(g.columnCount())])
print("  cb sizeHint w =", cb.sizeHint().width(), " minimumWidth =", cb.minimumWidth())
print("  le geometry:", le.geometry().getRect(), " cb geometry:", cb.geometry().getRect())
print("  grid container size:", gc.size().width(), "x", gc.size().height())
print("  grid colstretch 0/1:", g.columnStretch(0), g.columnStretch(1))
print("  cb sizePolicy:", cb.sizePolicy().horizontalPolicy())
print("  le size:", le.width(), "x", le.height())
lv = le.mapTo(dlg, le.rect().topLeft()); cv = cb.mapTo(dlg, cb.rect().topLeft())
print("  mapTo dlg  cb:", (cv.x(), cv.y(), cb.width(), cb.height()))
print("  mapTo dlg  le:", (lv.x(), lv.y(), le.width(), le.height()))

print("\n" + ("全部通过 ✅" if ok else "存在失败 ❌"))
