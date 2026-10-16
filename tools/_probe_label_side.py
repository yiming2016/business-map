# -*- coding: utf-8 -*-
"""探针：软件实际把站名画在了站点的哪一侧？和官方原图方位对不对得上？

用法：
    python tools/_probe_label_side.py            # 打印指定站 + 全局统计
    python tools/_probe_label_side.py --all      # 只打全局统计
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                       # noqa: E402

t = Path(tempfile.mkdtemp(prefix="chkside_"))
for n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / n).exists():
        import shutil
        shutil.copy(CDM.DATA_DIR / n, t / n)
(t / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = t / "stations.json"
CDM.LINES_FILE = t / "lines.json"
CDM.DATA_DIR = t

from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtTest import QTest                       # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402

WATCH = ["深大南", "深大", "科苑", "后海", "粤海门", "高新中", "车公庙", "世界之窗"]


def pump(n=8):
    for _ in range(n):
        QTest.qWait(20)
        QApplication.processEvents()


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(20)

    mv = None
    for attr in dir(win):
        o = getattr(win, attr, None)
        if o is not None and hasattr(o, "station_items"):
            mv = o
            print("找到地图视图属性: win.%s" % attr)
            break
    if mv is None:
        print("没找到 station_items，候选属性：")
        for attr in dir(win):
            o = getattr(win, attr, None)
            if o is not None and hasattr(o, "_side_lock"):
                print("   ", attr)
        return 2

    print("缩放 = %.3f   _side_lock 条数 = %d" % (mv.transform().m11(),
                                                len(getattr(mv, "_side_lock", {}))))
    print("-" * 78)
    print("%-8s %-8s %-8s %-26s %s" % ("站名", "官方", "实画", "标签矩形(scene)", "差"))
    for name in WATCH:
        it = mv.station_items.get(name)
        if it is None:
            print("%-8s 地图上没有这个站" % name)
            continue
        off = (it.data or {}).get("official_label_side") or "-"
        cur = it.label_side()
        r = it.label_scene_rect()
        cx, cy = it.pos().x(), it.pos().y()
        cxr, cyr = r.center().x() - cx, r.center().y() - cy
        print("%-8s %-8s %-8s (%7.0f,%7.0f) %7.0fx%-6.0f  dx=%7.1f dy=%7.1f"
              % (name, off, cur, r.left(), r.top(), r.width(), r.height(), cxr, cyr))

    # ---- 全局：实画方位 vs 官方方位 ----
    lock = getattr(mv, "_side_lock", {}) or {}
    same = diff = 0
    diff_list = []
    for sid, it in mv.station_items.items():
        off = (it.data or {}).get("official_label_side") or ""
        cur = it.label_side()
        if not off:
            continue
        if off == cur:
            same += 1
        else:
            diff += 1
            diff_list.append((sid, off, cur))
    tot = same + diff
    print("-" * 78)
    if tot:
        print("全局：有官方方位的 %d 站里，实画方位**和原图一致** %d 站（%.0f%%）、"
              "**不一致** %d 站（%.0f%%）"
              % (tot, same, same * 100.0 / tot, diff, diff * 100.0 / tot))
    print("_side_lock 里锁了 %d 站" % len(lock))
    print("前 25 个不一致的：")
    for sid, off, cur in diff_list[:25]:
        print("     %-10s 官方=%-7s 实画=%s" % (sid, off, cur))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
