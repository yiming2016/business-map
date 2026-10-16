# -*- coding: utf-8 -*-
"""一次性迁移：给**已经手动调过**的站补上 `label_side`（方位）。

为什么必须补：v2.6.60 之前只存了偏移（label_dx/dy），方位只活在内存里。
现在新版本会**读** label_side，老数据没有这个字段 ⇒ 方位会退回"官方初始方位"
⇒ 这批站的位置会在升级后**跳一下**（正是用户抱怨的那个跳）。
⇒ 用"当前排版挑出来的方位"补进去（同一份数据 + 同一套排版 ⇒ 就是用户
   拖动时看到的那个方位），位置就不会变。

★ 只**新增**一个字段，不改任何别的字段；写之前先备份。

用法：
    python tools/migrate_label_side_once.py            # 只看不动
    python tools/migrate_label_side_once.py --apply    # 写入（先备份）
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LIVE = ROOT.parent / "软件" / "data"          # ★ 用户正在用的那份
apply_ = "--apply" in sys.argv

import core.data_manager as CDM                       # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="miglbl_"))
(tmp / "covers").mkdir(exist_ok=True)
shutil.copy(LIVE / "stations.json", tmp / "stations.json")
shutil.copy(LIVE / "lines.json", tmp / "lines.json")
CDM.DATA_DIR = tmp
CDM.STATIONS_FILE = tmp / "stations.json"
CDM.LINES_FILE = tmp / "lines.json"

from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtTest import QTest                       # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402


def pump(n=20):
    for _ in range(n):
        QTest.qWait(20)
        QApplication.processEvents()


def main():
    doc = json.loads((LIVE / "stations.json").read_text(encoding="utf-8"))
    st = doc["stations"]
    need = [n for n, s in st.items()
            if (abs(float(s.get("label_dx") or 0)) > 0.01
                or abs(float(s.get("label_dy") or 0)) > 0.01)
            and not (s.get("label_side") or "")]
    print("=" * 70)
    print("需要补方位的站：%d 个（有手动偏移、但没有 label_side）" % len(need))
    if not need:
        print("没有要补的。")
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = None
    for attr in dir(win):
        o = getattr(win, attr, None)
        if o is not None and hasattr(o, "station_items"):
            mv = o
            break
    if mv is None:
        print("没找到地图视图")
        return 1

    got = {}
    miss = []
    for n in need:
        it = mv.station_items.get(n)
        if it is None:
            miss.append(n)
            continue
        got[n] = it.label_side()
    win.close()
    print("取到方位 %d 个，没找到图元 %d 个" % (len(got), len(miss)))
    for n in list(got)[:8]:
        print("   %-8s → %s" % (n, got[n]))

    if not apply_:
        print("（没写入。确认后加 --apply）")
        return 0

    bak = LIVE / ("stations.json.bak_label_side_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(LIVE / "stations.json", bak)
    for n, side in got.items():
        st[n]["label_side"] = side
    (LIVE / "stations.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[备份] %s" % bak.name)
    print("[写入] 补了 %d 个站的方位" % len(got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
