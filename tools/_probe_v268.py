"""v2.6.8 五处改动的现场探针（只读，不写真实数据）。

    1. 下拉文字居中（收起态 + 展开态）+ 挪到表头"线路"左侧
    2. 「设施」输入框挂到「出入口信息」标题右侧、删掉"设施"两个字
    3. 编辑页字段顺序：出入口信息 → 周边地标 → 备注 → 首末班车 → 公交换乘
    4. 出入口编号垂直居中
    5. 多行输入框高度自动拉伸（文字多少都刚好显示完、无内部滚动）
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import core.data_manager as dm_mod                                   # noqa: E402
_TMP = tempfile.mkdtemp(prefix="szmetro_probe_")
dm_mod.STATIONS_FILE = Path(_TMP) / "stations.json"
dm_mod.LINES_FILE = Path(_TMP) / "lines.json"
dm_mod.DATA_DIR = Path(_TMP)
_SRC = Path(__file__).resolve().parents[1] / "data"
import shutil                                                        # noqa: E402
shutil.copy(_SRC / "stations.json", dm_mod.STATIONS_FILE)
shutil.copy(_SRC / "lines.json", dm_mod.LINES_FILE)

from PySide6.QtWidgets import QApplication, QLabel                   # noqa: E402
from PySide6.QtCore import Qt                                        # noqa: E402
from PySide6.QtGui import QFontMetrics                               # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from core.schema import EDITABLE_FIELDS                              # noqa: E402
from ui.edit_dialog import EditDialog                                # noqa: E402
from ui.timetable_editor import TimetableEditor                      # noqa: E402
from ui.exits_editor import ExitsEditor                              # noqa: E402
from ui.autofit import fit_height, no_inner_scroll                   # noqa: E402

dm = dm_mod.get_data_manager()
SID = "车公庙"

print("=" * 70)
print("① 字段顺序（schema）")
print("=" * 70)
vis = [f for f in EDITABLE_FIELDS
       if f["key"] not in ("station_name", "description", "lines")]
print("  → " + "、".join(
    f.get("label") + ("(挂到exits)" if f.get("head_with") else "") for f in vis))

print()
print("=" * 70)
print("② 弹窗：字段实际出场顺序 + 设施挂位")
print("=" * 70)
dlg = EditDialog(station_id=SID, parent=None)
dlg.resize(760, 900)
dlg.show()
app.processEvents()
app.processEvents()

# 表单里每一行的"行首文字"
labels_order = []
for i in range(dlg.form_layout.rowCount()):
    item = dlg.form_layout.itemAt(i, dlg.form_layout.ItemRole.LabelRole)
    field = dlg.form_layout.itemAt(i, dlg.form_layout.ItemRole.FieldRole)
    txt = ""
    if item is not None and item.widget() is not None:
        txt = item.widget().text().strip()
    if not txt and field is not None and field.widget() is not None:
        labs = [lb.text().strip() for lb in field.widget().findChildren(QLabel)
                if lb.text().strip()]
        txt = labs[0] if labs else ""
    labels_order.append(txt or "(无标签)")
print("  出场顺序 → " + " | ".join(labels_order))

_fac = dlg._widgets["facilities"]
_ex = dlg._widgets["exits"]
_exbox = _ex.parentWidget()
print(f"  设施控件 parent = {type(_fac.parentWidget()).__name__}")
labs_head = [lb.text().strip() for lb in _fac.parentWidget().findChildren(QLabel)
             if lb.text().strip()]
print(f"  设施所在容器的标签 = {labs_head}")
_fy = _fac.mapTo(dlg, _fac.rect().center())
print(f"  设施框中心 y={_fy.y()}  出入口标题行的 y 应在其附近")
# 找"出入口信息"标签
_ex_lab = [lb for lb in _exbox.findChildren(QLabel)
           if lb.text().strip() == "出入口信息"]
if _ex_lab:
    _ly = _ex_lab[0].mapTo(dlg, _ex_lab[0].rect().center())
    print(f"  「出入口信息」中心 y={_ly.y()}  与设施框中心差 {abs(_ly.y()-_fy.y())}px")
    print(f"  设施框在标题右侧？ left(fac)={_fac.mapTo(dlg,_fac.rect().topLeft()).x()} "
          f"> right(label)={_ex_lab[0].mapTo(dlg,_ex_lab[0].rect().topRight()).x()} "
          f"→ {_fac.mapTo(dlg,_fac.rect().topLeft()).x() > _ex_lab[0].mapTo(dlg,_ex_lab[0].rect().topRight()).x()}")
_all_labs = [lb.text().strip() for lb in dlg.form_host.findChildren(QLabel)]
print(f"  整个表单里还有没有『设施』二字：{'设施' in _all_labs}")

print()
print("=" * 70)
print("③ 首末班车下拉：居中 + 在表头『线路』左侧")
print("=" * 70)
tt = dlg._widgets["timetable"]
cb = tt.date_combo
print(f"  下拉 count={cb.count()}  当前={cb.currentText()!r}")
le = cb.lineEdit()
print(f"  editable={cb.isEditable()}  内部 QLineEdit alignment={le.alignment()}")
print(f"    → 收起态居中？ {bool(le.alignment() & Qt.AlignHCenter)}")
for i in range(cb.count()):
    print(f"    项[{i}] {cb.itemText(i)!r} TextAlignmentRole="
          f"{cb.itemData(i, Qt.TextAlignmentRole)}")
# 表头"线路"标签 vs 下拉 的相对位置
hdr_labels = {}
for lb in tt.findChildren(QLabel):
    t = lb.text().strip()
    if t in ("线路", "方向", "首班", "末班") and t not in hdr_labels:
        hdr_labels[t] = lb
_lab_line = hdr_labels.get("线路")
if _lab_line is not None and cb is not None:
    cx = cb.mapTo(tt, cb.rect().center()).x()
    lx = _lab_line.mapTo(tt, _lab_line.rect().center()).x()
    cy = cb.mapTo(tt, cb.rect().center()).y()
    ly = _lab_line.mapTo(tt, _lab_line.rect().center()).y()
    print(f"  下拉中心 x={cx}  『线路』中心 x={lx}  → 下拉在左侧？ {cx < lx}")
    print(f"  下拉中心 y={cy}  『线路』中心 y={ly}  → 同一行？差 {abs(cy-ly)}px")
print()
print("=" * 70)
print("④ 出入口编号垂直居中")
print("=" * 70)
ex_ed = dlg._widgets["exits"]
if isinstance(ex_ed, ExitsEditor):
    print(f"  行数 {len(ex_ed.rows)}")
    for k, (tag_ed, txt_ed, *_rest) in enumerate(ex_ed.rows[:4]):
        tc = tag_ed.mapTo(ex_ed, tag_ed.rect().center()).y()
        xc = txt_ed.mapTo(ex_ed, txt_ed.rect().center()).y()
        print(f"  行{k} 编号中心 y={tc}  内容框中心 y={xc}  差 {abs(tc-xc)}px "
              f"（内容框高 {txt_ed.height()}）")

print()
print("=" * 70)
print("⑤ 多行输入框自动拉伸")
print("=" * 70)
for key in ("landmarks", "notes", "bus_transfer"):
    w = dlg._widgets.get(key)
    if w is None:
        continue
    h0 = w.height()
    w.setPlainText("短")
    app.processEvents()
    h1 = fit_height(w, 40)
    app.processEvents()
    w.setPlainText("长" * 400)
    app.processEvents()
    h2 = fit_height(w, 40)
    app.processEvents()
    print(f"  {key:14s} 初始 {h0} → 短文本 {h1} → 400字 {h2}  "
          f"无内部滚动={no_inner_scroll(w)}")
    w.setPlainText(str(dm.get_station(SID).get(key) or ""))
    app.processEvents()
    fit_height(w, 40)

print()
print("⑥ 简介框与封面图")
_d = dlg.desc_edit
print(f"  简介框高 {_d.height()}   封面按钮 {dlg.cover_btn.width()}x{dlg.cover_btn.height()}")

dlg.close()
app.processEvents()
print("\n探针结束。")
