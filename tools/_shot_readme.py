# -*- coding: utf-8 -*-
"""给 README 出图：离屏抓两张界面截图 → docs/screenshot.png / docs/screenshot_dialog.png

★ 为什么必须离屏（QT_QPA_PLATFORM=offscreen）：
  跑这个脚本时用户可能正在用电脑，任何抢焦点 / 弹窗都是打扰。离屏下
  `QWidget.grab()` 照样能把整个窗口渲染成 QPixmap，屏幕上一个像素都不闪。

用法（在 源码/ 下）：
    set QT_QPA_PLATFORM=offscreen
    ...\\python.exe tools/_shot_readme.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_VIEW_START", "1")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

# 抓图不写用户数据：拷一份到临时目录再跑
_TMP = Path(tempfile.mkdtemp(prefix="shotreadme_"))
for _n in ("stations.json", "lines.json", "schema.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                    # noqa: E402
from PySide6.QtGui import QFontDatabase, QFont                 # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402

OUT = ROOT / "docs"
OUT.mkdir(exist_ok=True)


def _load_cjk_font() -> str:
    """★ 离屏平台默认**没有中文字体**，站名/按钮会全渲染成方框（豆腐块）。
    这里把系统里的中文字体注册进去并设为全局字体，抓出来的图才不是一屏 □□。"""
    for cand in (r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\msyhl.ttc",
                 r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\simsun.ttc"):
        if os.path.exists(cand):
            fid = QFontDatabase.addApplicationFont(cand)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams:
                print(f"[FONT] 用中文字体 {cand} → {fams[0]}")
                return fams[0]
    print("[WARN] 没找到中文字体，图里的中文会是方框")
    return ""


def pump(n: int = 6) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    fam = _load_cjk_font()
    if fam:
        # ★ 光有雅黑还不够：界面里那些 emoji 图标（💾 保存、封面占位图标）会掉成
        #   方框。把 emoji / symbol 字体排进 fallback 列表，Qt 找不到字形时会往下找。
        f = QFont(fam, 9)
        for extra in (r"C:\Windows\Fonts\seguiemj.ttf",
                      r"C:\Windows\Fonts\seguisym.ttf"):
            if os.path.exists(extra):
                QFontDatabase.addApplicationFont(extra)
        f.setFamilies([fam, "Segoe UI Emoji", "Segoe UI Symbol"])
        app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(12)

    mv = win.map_view
    # 两个浮层都打开，看起来才像用户实际用的样子
    if not win.legend_panel.isVisible():
        win._on_toggle_legend(True)
    if not win.info_wrap.isVisible():
        win._on_toggle_info_panel()
    pump(6)
    mv.fit_map()
    pump(10)

    # 选中一个换乘大站，右侧面板就有内容
    for sid, it in mv.station_items.items():
        if it.data.get("station_name") in ("车公庙", "后海"):
            win.info_panel.show_station(sid)
            mv.select_station(sid, emit=False)
            mv.centerOn(it.pos())
            pump(12)
            break

    win.resize(1480, 900)
    pump(8)
    p1 = OUT / "screenshot.png"
    win.grab().save(str(p1))
    print(f"[OK] {p1}")

    # 第二张：站点编辑弹窗
    try:
        from ui.edit_dialog import EditDialog
        sid = next(iter(win.dm.all_stations().keys()))
        d = EditDialog(station_id=sid, parent=None)
        d.resize(760, 780)
        d.show()
        pump(12)
        p2 = OUT / "screenshot_dialog.png"
        d.grab().save(str(p2))
        print(f"[OK] {p2}")
        d.close()
    except Exception as e:
        print("[WARN] 编辑弹窗抓图失败：", repr(e))

    win.hide()
    return 0


if __name__ == "__main__":
    sys.exit(main())
