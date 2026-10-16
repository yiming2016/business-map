"""验证「所属线路」搬到顶栏后，展开面板仍能正常弹出、不被屏幕边缘切掉。"""
import sys
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication
from ui.edit_dialog import EditDialog

app = QApplication(sys.argv)
dlg = EditDialog(station_id="机场东")
dlg.show()
for _ in range(8): app.processEvents()

ls = dlg.lines_select
print(f"下拉控件 全局位置={ls.mapToGlobal(ls.rect().topLeft()).toTuple()} 尺寸={ls.width()}x{ls.height()}")
ls._toggle_popup()
for _ in range(6): app.processEvents()
pop = getattr(ls, "_popup", None)
if pop is None:
    print("[!!] 没找到 popup 属性，看看属性名"); print([a for a in dir(ls) if "pop" in a.lower()])
else:
    g = pop.geometry()
    scr = QGuiApplication.screenAt(pop.mapToGlobal(pop.rect().center())) or QGuiApplication.primaryScreen()
    sr = scr.availableGeometry()
    print(f"面板 实际={g.width()}x{g.height()} @ ({g.x()},{g.y()})  visible={pop.isVisible()}")
    print(f"屏幕可用区 = {sr.width()}x{sr.height()} @ ({sr.x()},{sr.y()})")
    inb = (g.x() >= sr.x() and g.y() >= sr.y()
           and g.x()+g.width() <= sr.x()+sr.width()
           and g.y()+g.height() <= sr.y()+sr.height())
    print(("[OK] 面板完全在屏幕内" if inb else "[!!] 面板超出屏幕，会被切掉"))
    # 面板应该贴在按钮附近
    btn = ls.mapToGlobal(ls.rect().bottomLeft())
    print(f"按钮底边全局 y={btn.y()}  面板 top={g.y()}  间距={g.y()-btn.y()}")
dlg.close()
