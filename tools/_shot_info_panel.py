# -*- coding: utf-8 -*-
"""右侧信息面板截图（v2.6.5 结构化改造前后对比用）。

用法：
    python tools/_shot_info_panel.py [站点名] [输出.png]

★ 只截不写：真实数据先拷到临时目录，绝不动用户数据。
★ 自带"图里真有内容"自检（40×40 网格数颜色种数）。
"""
import sys
import shutil
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import core.data_manager as dm  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="szmetro_shot_"))
_REAL = SRC / "data"
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy2(_REAL / _n, _TMP / _n)
dm.STATIONS_FILE = _TMP / "stations.json"
dm.LINES_FILE = _TMP / "lines.json"
dm.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402
from core.data_manager import get_data_manager  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

args = [a for a in sys.argv[1:]]
# --at <字段名>：先把滚动区滚到那个字段再截（面板很长，一屏截不全）
at = None
if "--at" in args:
    i = args.index("--at")
    at = args[i + 1]
    del args[i:i + 2]
sid = args[0] if args else "车公庙"
out = Path(args[1]) if len(args) >= 2 else SRC / "logs" / "_info_panel.png"
out.parent.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(12):
    app.processEvents()

panel = win.info_panel
panel.show_station(sid)
for _ in range(12):
    app.processEvents()

print("站点:", sid, " 面板宽:", panel.width())
sc = panel.findChild(QScrollArea)
vp_w = sc.viewport().width() if sc else panel.width()
print("可用宽:", vp_w)

# ★ 横向溢出检查：任何一个直接子控件都不该比可用宽更宽
bad = []
def _scan(w, depth=0):
    for ch in w.findChildren(object) if False else []:
        pass
for name in ("exits", "timetable", "facilities", "description"):
    wd = panel._widgets.get(name)
    if wd is None:
        continue
    print("   %-11s %-16s w=%-4d %s" % (
        name, type(wd).__name__, wd.width(),
        "OK" if wd.width() <= vp_w else "★溢出"))
    if wd.width() > vp_w:
        bad.append(name)

# ★ 别调 adjustSize()：那会把面板压回 sizeHint（实测截出来只有 287px 高），
#   而我们要的是"用户在真实窗口里看到的那一屏"。
if at and sc is not None:
    tw = panel._widgets.get(at)
    if tw is not None:
        sc.ensureWidgetVisible(tw, 0, 0)
for _ in range(6):
    app.processEvents()

pm = panel.grab()
if not pm.save(str(out)):
    print("[ERROR] 保存失败:", out)
    sys.exit(2)

from PySide6.QtGui import QImage  # noqa: E402
im = QImage(str(out))
cols = set()
for y in range(0, im.height(), max(1, im.height() // 40)):
    for x in range(0, im.width(), max(1, im.width() // 40)):
        cols.add(im.pixelColor(x, y).name())
print("截图:", out, im.width(), "x", im.height())
print("40x40 网格颜色种数 =", len(cols), "(1~2 种 = 没画出来)")
print("溢出字段:", bad)
win.close()
