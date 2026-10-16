# -*- coding: utf-8 -*-
"""只截「首末班车」那张表（放大 2×），专门用来看表头/列的相对位置。

用法：
    python tools/_shot_tt_only.py                 # 默认站 车公庙
    python tools/_shot_tt_only.py 机场东 out.png
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication           # noqa: E402

from ui.edit_dialog import EditDialog                # noqa: E402
from ui.timetable_editor import TimetableEditor      # noqa: E402

args = [a for a in sys.argv[1:]]
sid = args[0] if args else "车公庙"
out = Path(args[1]) if len(args) >= 2 else SRC / "logs" / "_tt_only.png"

app = QApplication(sys.argv)
dlg = EditDialog(station_id=sid)
dlg.show()
for _ in range(30):
    app.processEvents()

day = dlg.findChildren(TimetableEditor)
print("找到 TimetableEditor 数 =", len(day))
if not day:
    raise SystemExit("没找到")
tt = day[0]
for i, t in enumerate(day):
    print(f"  [{i}] visible={t.isVisible()} size={t.width()}x{t.height()} "
          f"compact={t.compact} slot={getattr(t, '_slot', None)} "
          f"COLS={t.COLS}")

pm = tt.grab()
pm = pm.scaled(pm.width() * 2, pm.height() * 2)
out.parent.mkdir(parents=True, exist_ok=True)
pm.save(str(out))
print(f"[OK] {out}  ({pm.width()}x{pm.height()} 放大 2×)")
