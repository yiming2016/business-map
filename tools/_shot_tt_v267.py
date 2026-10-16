# -*- coding: utf-8 -*-
"""给「首末班车」那一块单独截图（v2.6.7：下拉 + 表头对齐 改完自检用）。

用法：
    python tools/_shot_tt_v267.py [站名] [日期类型下标]

★ 自带两条"图里是不是真的有东西"的自检：
    ① 非底色像素占比（渲染失败的话画布原样返回，断言会永远通过）
    ② 40×40 网格数颜色种数（1~2 种 = 黑屏/纯色块）
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QTimer, QPoint                 # noqa: E402
from PySide6.QtGui import QImage, QColor                  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea   # noqa: E402

from ui.edit_dialog import EditDialog                     # noqa: E402

sid = sys.argv[1] if len(sys.argv) > 1 else "车公庙"
idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
out_dir = SRC / "logs"
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / f"_v267_tt_{sid}_{idx}.png"

app = QApplication(sys.argv)
dlg = EditDialog(station_id=sid)
dlg.show()


def shoot():
    dlg.raise_()
    app.processEvents()
    tt = dlg._widgets["timetable"]
    tt.date_combo.setCurrentIndex(idx)
    app.processEvents()

    # 把滚动区滚到"首末班车"这一行
    box = tt.parentWidget()
    try:
        area = box
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            area.ensureWidgetVisible(box)
            app.processEvents()
    except Exception:
        pass

    pm = dlg.grab()
    top_left = box.mapTo(dlg, QPoint(0, 0))
    crop = pm.copy(top_left.x(), top_left.y(), box.width(), box.height())
    big = crop.scaled(crop.width() * 2, crop.height() * 2)
    ok_save = big.save(str(out))

    # ---------- 自检：图里真有东西 ----------
    img = big.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()
    bg = img.pixelColor(2, 2)
    non_bg = 0
    colors = {}
    for y in range(0, h, max(1, h // 40)):
        for x in range(0, w, max(1, w // 40)):
            c = img.pixelColor(x, y)
            if c != bg:
                non_bg += 1
            colors[c.rgb()] = 1
    total = len(range(0, h, max(1, h // 40))) * len(range(0, w, max(1, w // 40)))
    print(f"[OK] {out}  save={ok_save}  {big.width()}x{big.height()}")
    print(f"     日期类型 = {tt.current_date()!r}（下拉共 {tt.date_combo.count()} 项）")
    print(f"     非底色像素 {non_bg}/{total} = {non_bg / max(1, total):.1%}"
          f"（<1% 说明根本没画上）")
    print(f"     40×40 网格颜色种数 = {len(colors)}（1~2 种 = 黑屏/纯色块）")
    print(f"     可见分组数 = {sum(1 for b in tt._group_boxes if b.isVisible())}")
    app.quit()


QTimer.singleShot(700, shoot)
sys.exit(app.exec())
