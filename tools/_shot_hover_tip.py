# -*- coding: utf-8 -*-
"""悬浮提示（HoverTip）截图 + 结构自检（v2.6.6：站名与线路并成一排）。

用法：
    python tools/_shot_hover_tip.py [站点名] [输出.png]

★ 只截不写：真实数据拷到临时目录，不动用户数据。
★ 自带"图里真有内容"自检（数非底色像素）。
"""
import sys
import shutil
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import core.data_manager as dm  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="szmetro_tip_"))
_REAL = SRC / "data"
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy2(_REAL / _n, _TMP / _n)
dm.STATIONS_FILE = _TMP / "stations.json"
dm.LINES_FILE = _TMP / "lines.json"
dm.DATA_DIR = _TMP

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from core.data_manager import get_data_manager  # noqa: E402
from ui.tooltip import HoverTip  # noqa: E402

args = [a for a in sys.argv[1:]]
sid = args[0] if args else "车公庙"
out = Path(args[1]) if len(args) >= 2 else SRC / "logs" / "_hover_tip.png"
out.parent.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
st = (get_data_manager().all_stations() or {}).get(sid)
if st is None:
    print("[ERROR] 没有这个站:", sid)
    sys.exit(2)

tip = HoverTip()
tip.show_for(QPoint(300, 300), st)
for _ in range(10):
    app.processEvents()

name = st.get("station_name", "")
print("站点:", sid, " 是否换乘:", bool(st.get("is_transfer")))
print("  lbl_title.text() =", repr(tip.lbl_title.text()))
print("  lbl_lines.text() =", repr(tip.lbl_lines.text()))

# ★ 一行判据：站名与线路标签的竖直区间必须有重叠（在同一排）
a, b = tip.lbl_title.geometry(), tip.lbl_lines.geometry()
ov = min(a.bottom(), b.bottom()) - max(a.top(), b.top())
print("  竖直重叠 =", ov, "px（>0 才是同一排）")
print("  左右关系：站名 right =", a.right(), " 线路 left =", b.left())

# ★ 去掉 📍 / 保留 🔄
print("  有 📍(定位图标) =", "\U0001F4CD" in tip.lbl_title.text(), "（应为 False）")
if bool(st.get("is_transfer")):
    print("  有 🔄(换乘图标) =", "\U0001F504" in tip.lbl_title.text(), "（应为 True）")

pm = tip.grab()
if not pm.save(str(out)):
    print("[ERROR] 保存失败:", out)
    sys.exit(2)
im = QImage(str(out))
nonbg = 0
for y in range(0, im.height(), 2):
    for x in range(0, im.width(), 2):
        c = im.pixelColor(x, y)
        if c.red() + c.green() + c.blue() > 30:
            nonbg += 1
print("截图:", out, im.width(), "x", im.height(), " 非底色采样点 =", nonbg)
