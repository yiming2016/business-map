# -*- coding: utf-8 -*-
"""量右侧信息面板的实际可用宽度（决定结构化编辑器能不能塞进去）。

用法：
    python tools/_measure_info_panel.py

★ 只量不写：不碰用户数据（data_manager 指到临时目录）。
"""
import sys
import shutil
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

# ★ 测试脚本不许写真实数据：把真实数据**拷一份**到临时目录再指过去
import core.data_manager as dm  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="szmetro_probe_"))
_REAL = SRC / "data"
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy2(_REAL / _n, _TMP / _n)
dm.STATIONS_FILE = _TMP / "stations.json"
dm.LINES_FILE = _TMP / "lines.json"
dm.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication, QScrollArea, QPlainTextEdit  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from core.schema import EDITABLE_FIELDS  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1480, 900)
win.show()
for _ in range(10):
    app.processEvents()

panel = win.info_panel
print("InfoPanel.width          =", panel.width())
print("InfoPanel.minimumWidth   =", panel.minimumWidth())
sc = panel.findChild(QScrollArea)
print("面板滚动区 viewport 宽   =", sc.viewport().width() if sc else "(无)")

# 找一个有出入口 + 首末班车的站，展示出来再量
from core.data_manager import get_data_manager  # noqa: E402
d = get_data_manager().all_stations()
cand = [(k, v) for k, v in d.items()
        if (v.get("exits") or "").strip() and (v.get("timetable") or "").strip()]
print("同时有出入口+首末班车的站数 =", len(cand))
if cand:
    sid = cand[0][0]
    print("用样例站:", sid)
    panel.show_station(sid)
    for _ in range(10):
        app.processEvents()
    for f in EDITABLE_FIELDS:
        w = panel._widgets.get(f["key"])
        if w is None:
            continue
        if f["key"] in ("exits", "timetable", "facilities", "description"):
            print("   %-12s %-16s 宽=%4d 高=%4d" % (
                f["key"], type(w).__name__, w.width(), w.height()))
    print("表单可视宽度（form_host）= ", panel.form_host.width()
          if hasattr(panel, "form_host") else "(无 form_host)")

print("\n[临时目录]", _TMP)
win.close()
