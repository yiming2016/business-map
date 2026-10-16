# -*- coding: utf-8 -*-
"""把 ⚙️ 设置弹窗渲染成 png（离屏，不弹任何窗口）—— 改版前后对比用。

用法：python tools/_shot_settings.py 输出路径.png
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
os.environ.setdefault("METROEDITOR_NO_VIEW_START", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from pathlib import Path                                   # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402

app = QApplication(sys.argv)
try:                       # 离屏也要能画出中文（否则截图全是方框）
    from PySide6.QtGui import QFont
    for fam in ("Microsoft YaHei", "SimHei", "SimSun"):
        f = QFont(fam, 9)
        if f.exactMatch() or fam:
            app.setFont(f)
            break
except Exception:
    pass

from ui.image_mode import load_settings                    # noqa: E402
from ui.image_settings_dialog import ImageSettingsDialog   # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "_settings_shot.png"
d = str(Path(_ROOT) / "data")
dlg = ImageSettingsDialog(None, load_settings(d), d)
dlg.show()
for _ in range(20):
    app.processEvents()
    QTest.qWait(10)
pm = dlg.grab()
pm.save(out)
print(f"[OK] {out}  {pm.width()}x{pm.height()}  弹窗 {dlg.width()}x{dlg.height()}")
