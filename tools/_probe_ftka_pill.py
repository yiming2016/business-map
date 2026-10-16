# -*- coding: utf-8 -*-
"""_probe_ftka_pill.py —— 离屏渲染福田口岸，验证横向胶囊 + 单一文字。

v2.6.65：福田口岸 pill={ang:0,len:117,dx:44.5,merge:1} ——
  · 主图元画一个横跨 4/10 号线两站体的横向胶囊（中心在两体中点）；
  · 副站体圆点 + 灰虚线不再画（build_link_items 的 merge 分支）；
  · 全站只剩主图元那一份"福田口岸"文字。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

OUT = Path(r"C:/Users/29773/WorkBuddy/2026-09-13-00-34-00/_ftka_after.png")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    app.processEvents()
    mv = win.map_view
    win.dm.save = lambda *a, **k: None   # 测试绝不写盘

    mv.centerOn(QPointF(3564.5, 5949.0))   # 胶囊中心
    app.processEvents()
    mv.zoom_to_station("福田口岸", target_scale=1.0)
    app.processEvents()
    app.processEvents()
    pm = mv.viewport().grab()
    pm.save(str(OUT))
    print("saved:", OUT, pm.width(), "x", pm.height())

    # ---- 断言 1：场景里"福田口岸"文字标签只有 1 份 ----
    n_lbl = 0
    for it in mv.scene_.items():
        lbl = getattr(it, "label", None)
        if lbl is not None and getattr(lbl, "text", "") and lbl.text() == "福田口岸":
            # HaloLabel 是图元，text() 才是文本； station_items 的 label 都算
            n_lbl += 1
    # HaloLabel 本身也是 scene item（有 text()），上面按 owner.item 的 label 找；
    # 再按图元直接数一遍（HaloLabel.toPlainText）
    n_item = 0
    for it in mv.scene_.items():
        if type(it).__name__ == "HaloLabel" and it.text() == "福田口岸":
            n_item += 1
    print("labels(按owner) =", n_lbl, " labels(按图元) =", n_item)

    # ---- 断言 2：副站体图元不存在 ----
    alts = [k for k in getattr(mv, "alt_items", {}) if k.startswith("福田口岸")]
    print("alt_items(福田口岸) =", alts)

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
