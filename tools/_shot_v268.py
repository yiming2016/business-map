"""v2.6.8 改动区域的截图（弹窗内控件直接 grab，不走 PrintWindow）。

★ 每张图都要自带"图里真有东西"的自检：
  数非底色像素占比 + 40×40 网格的颜色种数（1~2 种 = 黑屏，正常几十上百种）。
  不然 `save()` 返回 False 也不报错，会让人以为截图成功了。
"""

from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.data_manager as dm_mod                                   # noqa: E402
_TMP = Path(tempfile.mkdtemp(prefix="szmetro_shot_"))
dm_mod.STATIONS_FILE = _TMP / "stations.json"
dm_mod.LINES_FILE = _TMP / "lines.json"
dm_mod.DATA_DIR = _TMP
_SRC = Path(__file__).resolve().parents[1] / "data"
shutil.copy(_SRC / "stations.json", dm_mod.STATIONS_FILE)
shutil.copy(_SRC / "lines.json", dm_mod.LINES_FILE)

from PySide6.QtWidgets import QApplication                            # noqa: E402
from PySide6.QtGui import QImage                                      # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from ui.edit_dialog import EditDialog                                 # noqa: E402
from ui.info_panel import InfoPanel                                   # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "logs"
SID = "车公庙"


def stats(pm, tag: str):
    img = pm.toImage()
    w, h = img.width(), img.height()
    colors = set()
    non_bg = 0
    total = 0
    step = max(1, w // 40)
    for y in range(0, h, max(1, h // 40)):
        for x in range(0, w, step):
            c = img.pixelColor(x, y)
            colors.add((c.red() // 16, c.green() // 16, c.blue() // 16))
    # 非底色（不是纯白）像素占比
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            c = img.pixelColor(x, y)
            total += 1
            if not (c.red() > 248 and c.green() > 248 and c.blue() > 248):
                non_bg += 1
    ratio = non_bg / max(1, total)
    print(f"  {tag}: {w}x{h}  颜色种数={len(colors)}  非底色占比={ratio:.1%}")
    ok = len(colors) >= 8 and ratio > 0.02
    print(f"    → {'有内容 ✅' if ok else '⚠️ 疑似空白'}")
    return ok


def save(pm, name: str) -> bool:
    p = OUT / name
    ok = pm.save(str(p))
    print(f"  保存 {p.name}: {'OK' if ok else '失败!!'}  ({p.stat().st_size if p.exists() else 0} bytes)")
    return ok


print("=" * 66)
print("v2.6.8 截图")
print("=" * 66)

dlg = EditDialog(station_id=SID)
dlg.resize(760, 900)
dlg.show()
app.processEvents()
for _ in range(10):
    app.processEvents()

# ① 表单顶部：出入口信息（右侧挂设施）+ 编号垂直居中
_ex = dlg._widgets["exits"]
_ex.relayout_rows()
app.processEvents()
_shot1 = _ex.parentWidget().grab()
print("\n① 「出入口信息」整块（标题右侧是设施输入框、编号垂直居中）")
stats(_shot1, "出入口块")
save(_shot1, "_v268_exits.png")

# ② 首末班车：表头 + 下拉（三种日期类型各一张）
_tt = dlg._widgets["timetable"]
for i in range(_tt.date_combo.count()):
    _tt.date_combo.setCurrentIndex(i)
    app.processEvents()
    img = _tt.grab()
    nm = _tt.date_combo.currentText()
    print(f"\n②-{i} 首末班车（{nm}）")
    stats(img, f"  表格")
    save(img, f"_v268_tt_{i}.png")

# ③ 右侧面板（紧凑模式，验证下拉没有把面板撑爆）
panel = InfoPanel()
panel.resize(380, 720)
panel.show()
panel.show_station(SID)
app.processEvents()
for _ in range(6):
    app.processEvents()
_ptt = panel._widgets["timetable"]
_ptt.relayout_rows() if hasattr(_ptt, "relayout_rows") else None
app.processEvents()
print("\n③ 右侧信息面板整块")
_pimg = panel.grab()
stats(_pimg, "面板")
save(_pimg, "_v268_panel.png")

print("\n窗口标题:", dlg.windowTitle())
dlg.close()
panel.close()
print("截图完成。")
