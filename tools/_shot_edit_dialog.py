# -*- coding: utf-8 -*-
"""给编辑弹窗截图（改 UI 前后对比用）。

用法：
    python tools/_shot_edit_dialog.py                 # 编辑模式，默认站"机场东"
    python tools/_shot_edit_dialog.py 车公庙 出.png
    python tools/_shot_edit_dialog.py --new 出.png    # 新建模式
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer, QRect            # noqa: E402

from ui.edit_dialog import EditDialog               # noqa: E402

args = [a for a in sys.argv[1:]]
is_new = "--new" in args
args = [a for a in args if a != "--new"]
# --h 900：把弹窗拉高一点再截，方便一次看全所有字段（改 UI 自检用）
height = None
if "--h" in args:
    i = args.index("--h")
    height = int(args[i + 1])
    del args[i:i + 2]
sid = "" if is_new else (args[0] if args else "机场东")
out = Path(args[-1]) if len(args) >= 2 or (is_new and args) else SRC / "logs" / "_edit_dialog.png"
if is_new and args and not args[-1].endswith(".png"):
    out = Path(args[-1])
if not str(out).endswith(".png"):
    out = SRC / "logs" / "_edit_dialog.png"
out.parent.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
dlg = EditDialog(station_id=sid)
if height:
    dlg.resize(560, height)
dlg.show()


def shoot():
    dlg.raise_()
    app.processEvents()
    pm = dlg.grab()
    pm.save(str(out))
    print(f"[OK] {out}  ({pm.width()}x{pm.height()})")

    # 顶栏单独放大截一张（检查封面图按钮 / 名称框 / 简介的相对关系）
    top_h = max(dlg.cover_btn.height(), 150) + 26
    om = dlg.grab(QRect(0, 0, dlg.width(), top_h))
    out2 = out.with_name(out.stem + "_top.png")
    om.scaled(om.width() * 2, om.height() * 2).save(str(out2))
    print(f"[OK] {out2}  ({om.width() * 2}x{om.height() * 2} 放大 2×)")

    # 圆角自检：把窗口放在一块纯色背景上截屏，看四角是不是被挖掉了。
    # （dlg.grab() 只画控件自己，看不出窗口外形）
    if "--corners" in sys.argv:
        scr = QApplication.primaryScreen()
        full = scr.grabWindow(0)
        g = dlg.mapToGlobal(QRect(0, 0, 1, 1).topLeft())
        full.copy(g.x(), g.y(), dlg.width(), dlg.height()).save(
            str(out.with_name(out.stem + "_corners.png")))
        print(f"[OK] 圆角截图（连桌面背景）: {out.with_name(out.stem + '_corners.png')}")
    print(f"     cover_btn={dlg.cover_btn.width()}x{dlg.cover_btn.height()} "
          f"iconSize={dlg.cover_btn.iconSize().width()} "
          f"name.w={dlg.name_edit.width()} desc.w={dlg.desc_edit.width()}")

    # 顺带把弹窗里出现的"站点名称/station_id"文本打出来，便于核对重复次数
    from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit
    hits = []
    for w in dlg.findChildren(QLabel):
        t = w.text().strip()
        if t:
            hits.append(f"QLabel   : {t!r}")
    for w in dlg.findChildren(QLineEdit):
        hits.append(f"QLineEdit: {w.text()!r}  readOnly={w.isReadOnly()}  ph={w.placeholderText()!r}")
    for w in dlg.findChildren(QPlainTextEdit):
        hits.append(f"QPlainText: {w.toPlainText()[:20]!r}")
    print("--- 弹窗里的文本控件 ---")
    for h in hits:
        print("   ", h)
    app.quit()


QTimer.singleShot(600, shoot)
sys.exit(app.exec())
