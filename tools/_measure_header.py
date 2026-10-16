"""量一下编辑弹窗顶栏各控件的真实高度，用来决定封面图该做多大。

用法: python tools/_measure_header.py
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication
from ui.edit_dialog import EditDialog

app = QApplication.instance() or QApplication(sys.argv)

dlg = EditDialog(station_id="")
dlg.show()
app.processEvents()
app.processEvents()

n = dlg.name_edit
d = dlg.desc_edit
b = dlg.cover_btn
hr = dlg.header_right

print(f"名称框  top={n.mapTo(dlg, n.rect().topLeft()).y():4d}  h={n.height():4d}  w={n.width()}")
print(f"简介框  top={d.mapTo(dlg, d.rect().topLeft()).y():4d}  h={d.height():4d}  w={d.width()}")
print(f"封面钮  top={b.mapTo(dlg, b.rect().topLeft()).y():4d}  h={b.height():4d}  w={b.width()}")
print(f"右列    top={hr.mapTo(dlg, hr.rect().topLeft()).y():4d}  h={hr.height():4d}")
print(f"右列距简介框底 = {hr.mapTo(dlg, hr.rect().bottomLeft()).y() - d.mapTo(dlg, d.rect().bottomLeft()).y()}")

d_top = d.mapTo(dlg, d.rect().topLeft()).y()
d_bot = d.mapTo(dlg, d.rect().bottomLeft()).y()
b_top = b.mapTo(dlg, b.rect().topLeft()).y()
b_bot = b.mapTo(dlg, b.rect().bottomLeft()).y()
print()
print(f"当前: 图片高={b.height()}  简介框高={d.height()}  底边差={d_bot - b_bot}")
print(f"若图片高=简介框高({d.height()})，图片需再长 {d.height() - b.height()}px")
print(f"边长比 {d.height()/b.height():.3f}  面积比 {(d.height()/b.height())**2:.3f}")

dlg.close()
