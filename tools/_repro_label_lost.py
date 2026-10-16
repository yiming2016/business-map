# -*- coding: utf-8 -*-
"""复现「改完站名位置，关掉再打开就丢了」——**两个独立进程**才叫"关掉再打开"。

同一个进程里 new 两个 MainWindow 不算（数据管理器是单例，第二次可能直接读到
内存里那份脏数据，等于没关过）。所以这里用 `--step drag` / `--step reopen`
两步，由外层跑**两次进程**，中间真的落盘一次。

用法（外层）：
    python tools/_repro_label_lost.py --step drag   --data <temp> --out a.json
    python tools/_repro_label_lost.py --step reopen --data <temp> --out b.json

`--drag` 可指定要拖哪些站：默认 4 个（2 个用户调过的 + 2 个没调过的）。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                       # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--step", required=True, choices=("drag", "reopen"))
p.add_argument("--data", required=True)
p.add_argument("--out", required=True)
p.add_argument("--drag", default="世界之窗,车公庙,深大,上屋")
p.add_argument("--dx", type=float, default=60.0)
p.add_argument("--dy", type=float, default=-80.0)
args = p.parse_args()

CDM.DATA_DIR = Path(args.data)
CDM.STATIONS_FILE = CDM.DATA_DIR / "stations.json"
CDM.LINES_FILE = CDM.DATA_DIR / "lines.json"

from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtTest import QTest                       # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402


def pump(n=10):
    for _ in range(n):
        QTest.qWait(20)
        QApplication.processEvents()


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(30)
    mv = None
    for attr in dir(win):
        o = getattr(win, attr, None)
        if o is not None and hasattr(o, "station_items"):
            mv = o
            break
    if mv is None:
        print("没找到地图视图")
        return 1

    if args.step == "drag":
        for name in args.drag.split(","):
            name = name.strip()
            it = mv.station_items.get(name)
            if it is None:
                print("  [跳过] 没有这个站：%s" % name)
                continue
            it.set_label_off(args.dx, args.dy)
            win._on_label_moved(it.station_id)     # ★ 走真实拖动结束那条保存链路
            pump(4)
        win._save_data()

    res = {"step": args.step, "scale": round(float(mv._scale), 4), "items": {}}
    for name in args.drag.split(","):
        name = name.strip()
        it = mv.station_items.get(name)
        if it is None:
            continue
        r = it.label_scene_rect()
        res["items"][name] = {
            "cx": round(float(r.center().x()), 1),
            "cy": round(float(r.center().y()), 1),
            "off": [round(float(it.label_off().x()), 1), round(float(it.label_off().y()), 1)],
            "side": str(it.label_side()),
        }
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("[%s] scale=%.3f  %s" % (args.step, res["scale"], json.dumps(res["items"], ensure_ascii=False)))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
