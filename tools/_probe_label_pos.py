# -*- coding: utf-8 -*-
"""探针：软件**实际把每个站名画在了哪里**（场景坐标），导成 JSON 做 A/B 对比。

★ 为什么要这个：用户问「你每次修改都在乱动我已经调整好的文字吗？」
  光看数据文件（label_dx/dy 没被写过）不够 —— 站名最终位置 =
  自动摆位（可能受线路走向影响）+ 用户偏移。必须**问软件**才知道。

★ 数据一律先拷到 temp 再跑（绝不写用户正在用的那份）。

用法：
    python tools/_probe_label_pos.py out.json --src ../软件/data
    python tools/_probe_label_pos.py out.json --src ../软件/data --no-trace
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                       # noqa: E402

args = sys.argv[1:]
out = Path(args[0]) if args else ROOT / "_tmp_label_pos.json"
src = ROOT / "data"
if "--src" in args:
    src = (ROOT / args[args.index("--src") + 1]).resolve()
no_trace = "--no-trace" in args

t = Path(tempfile.mkdtemp(prefix="chklbl_"))
for n in ("stations.json", "lines.json"):
    if (src / n).exists():
        shutil.copy(src / n, t / n)
(t / "covers").mkdir(exist_ok=True)
if no_trace:                       # ★ 只改 temp 里的副本，源文件一个字节都不动
    d = json.loads((t / "lines.json").read_text(encoding="utf-8"))
    d["traced"] = {}
    (t / "lines.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
CDM.STATIONS_FILE = t / "stations.json"
CDM.LINES_FILE = t / "lines.json"
CDM.DATA_DIR = t

from PySide6.QtWidgets import QApplication             # noqa: E402
from PySide6.QtTest import QTest                       # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402


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
            break
    if mv is None:
        print("没找到地图视图")
        return 1
    res = {}
    for name, it in mv.station_items.items():
        try:
            r = it.label_scene_rect()
            vis = it.isVisible()
        except Exception:
            continue
        res[name] = [round(float(r.center().x()), 1), round(float(r.center().y()), 1),
                     round(float(r.width()), 1), round(float(r.height()), 1), bool(vis)]
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("[导出] %d 个站名位置 → %s  （源数据 %s，%s）"
          % (len(res), out.name, src.name, "清空 traced" if no_trace else "带 traced"))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
