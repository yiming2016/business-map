# -*- coding: utf-8 -*-
"""
tools/_shot_v269.py
===================
v2.6.9 出图：站名避让线路 / 换乘站专属图标 / 日期下拉。

★ 出图后必须验"图里真有内容"：`QPixmap.save()` 失败只是返回 False 不报错，
  渲染失败画布原样返回 ⇒ 断言会永远通过（项目里踩过，见 MEMORY §5.7）。
  这里数 40×40 网格上的颜色种数：1~2 种 = 黑屏/纯色，正常 100+ 种。
★ QPixmap 没有 pixelColor，必须 `.toImage()`。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint, QRect                  # noqa: E402
from PySide6.QtGui import QFont                               # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

LOG = ROOT / "logs"
LOG.mkdir(exist_ok=True)


def pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def stats(pm, name: str) -> bool:
    img = pm.toImage()
    cols = set()
    for i in range(40):
        for j in range(40):
            x = int(img.width() * (i + 0.5) / 40)
            y = int(img.height() * (j + 0.5) / 40)
            cols.add(img.pixelColor(x, y).rgb())
    ok = len(cols) >= 8
    print("      %-22s %dx%d  颜色种数 %4d  ⇒ %s"
          % (name, pm.width(), pm.height(), len(cols), "有内容" if ok else "★疑似空图"))
    return ok


def save(pm, name: str) -> bool:
    path = LOG / name
    good = pm.save(str(path))
    print("      %s → %s（%s）" % (name, path, "已保存" if good else "★保存失败"))
    return good and stats(pm, name)


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    allok = True

    def set_scale(scale):
        mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                                 mv.viewport().rect().center())
        mv._sync_zoom_state()
        mv._apply_station_scale_all()
        pump(10)
        mv._invalidate_nn()
        mv._update_label_visibility()
        pump(14)

    print("\n===== 1 站名避让线路 =====")
    floor = mv._min_scale_for_viewport()
    set_scale(floor)
    allok &= save(mv.grab(), "_v269_fit.png")
    set_scale(1.0)
    allok &= save(mv.grab(), "_v269_z100.png")
    # 缩到最小时切几块密集区放大 3 倍看（全图缩略图看不出"字压在线上"）
    set_scale(floor)
    full = mv.grab()
    img = full.toImage()
    W, H = img.width(), img.height()
    for name, fx, fy in (("mid", 0.35, 0.35), ("cbd", 0.55, 0.62), ("ne", 0.62, 0.28)):
        w = int(W * 0.26)
        h = int(H * 0.26)
        x = int(W * fx)
        y = int(H * fy)
        crop = img.copy(x, y, w, h).scaled(w * 3, h * 3, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
        from PySide6.QtGui import QPixmap as _PM
        allok &= save(_PM.fromImage(crop), "_v269_fit_%s.png" % name)

    print("\n===== 2 换乘站专属图标（放大看）=====")
    # 找一个换乘站，把视图居中到它并放大
    tr = [it for it in mv.station_items.values() if it.is_transfer]
    tr.sort(key=lambda it: it.station_id)
    pick = tr[0] if tr else None
    if pick is not None:
        set_scale(4.0)
        mv.centerOn(pick.pos())
        pump(20)
        mv._apply_station_scale_all()
        pump(20)
        allok &= save(mv.grab(), "_v269_transfer_%s.png" % pick.station_id)
        print("      换乘站：%s（共 %d 个换乘站）" % (pick.station_id, len(tr)))
        # 再把该站本身放大成一张特写（用 sprite 渲染路径，验证贴图也是新图标）
        set_scale(4.0)
        pump(10)
        pm = pick.render_sprite(3.0) or None
        spr = getattr(pick, "_sprite", None)
        if spr is not None:
            allok &= save(spr[0], "_v269_transfer_sprite.png")

    print("\n===== 3 日期类型下拉（编辑弹窗里那颗胶囊）=====")
    from ui.edit_dialog import EditDialog
    dlg = EditDialog(station_id="机场东", parent=win)
    dlg.show()
    pump(30)
    tt = None
    from ui.timetable_editor import TimetableEditor
    for w in dlg.findChildren(TimetableEditor):
        tt = w
        break
    if tt is not None and tt.date_combo is not None:
        cb = tt.date_combo
        allok &= save(cb.grab(), "_v269_combo.png")
        # 顺手出三种日期类型各一张（看配色有没有跟着变）
        for i in range(cb.count()):
            cb.setCurrentIndex(i)
            pump(6)
            allok &= save(cb.grab(), "_v269_combo_%d.png" % i)
    else:
        print("      ★ 没找到日期下拉")

    win.close()
    pump()
    print("\n===== 结果：%s =====" % ("全部有内容" if allok else "★有空图/失败"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
