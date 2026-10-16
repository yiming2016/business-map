# -*- coding: utf-8 -*-
"""只读诊断：「文字改了之后可能不被保存」到底是哪条路丢的？

三件事实测（全部跑在 temp 数据上，不碰真实 data）：
  A 改了文字**不点保存**就切到别的站  ⇒ 改动的字还在不在？
  B 改了文字**点了保存**，但改的是**站名**  ⇒ stations 的键 / 线路站序同步了吗？
    重开（重新读 json）之后还对得上吗？
  C 改了文字**不点保存**就关窗口      ⇒ 改动的字还在不在？

用法：
    python tools/_probe_text_save.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="textsave_"))
for _n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

A, B = "车公庙", "老街"
NEW = "车公庙新名"


def pump(n=8):
    for _ in range(n):
        QTest.qWait(10)
        QApplication.processEvents()


def snap_json():
    """重新读一次落盘文件（= 模拟重开软件）"""
    st = json.loads((_TMP / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((_TMP / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    return st, lines


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(12)
    ip = win.info_panel
    dm = CDM.get_data_manager()

    print("=" * 72)
    print("A  改了文字【不点保存】就切到别的站")
    print("=" * 72)
    ip.show_station(A)
    pump(6)
    w = ip._widgets.get("station_name")
    if w is None:
        print("  ！找不到 station_name 控件")
        return 1
    old = w.text()
    print("  改前：%s" % old)
    w.setText(NEW)
    pump(4)
    print("  输入框改成：%s（**不点保存**）" % NEW)
    ip.show_station(B)              # ← 切到别的站
    pump(8)
    print("  已切到「%s」，面板标题=%s" % (B, ip.title.text()))
    ip.show_station(A)              # 切回来
    pump(8)
    back = ip._widgets["station_name"].text()
    print("  切回「%s」后输入框 = %r" % (A, back))
    st, _ = snap_json()
    print("  JSON 里 %r 的 station_name = %r" % (A, st.get(A, {}).get("station_name")))
    d1 = dm.all_stations().get(A, {})
    print("  数据层 %r 的 station_name = %r" % (A, d1.get("station_name")))
    print("  → 结论：%s" % ("★ 改动丢了（用户没点保存，切站就静默丢弃）"
                            if back != NEW and d1.get("station_name") != NEW
                            else "改动还在"))

    print()
    print("=" * 72)
    print("B  改了站名并【点保存】—— 键 / 线路站序同步了吗")
    print("=" * 72)
    ip.show_station(A)
    pump(6)
    ip._widgets["station_name"].setText(NEW)
    pump(4)
    ip._on_save()
    pump(8)
    st, lines = snap_json()
    print("  stations 里【新名】作为键存在？ %s" % (NEW in st))
    print("  stations 里【旧名】作为键还在？ %s" % (A in st))
    if A in st:
        print("    旧名那条记录的 station_name = %r" % st[A].get("station_name"))
    hit = []
    for L in lines:
        seq = L.get("stations") or []
        if A in seq:
            hit.append((str(L.get("id")), "旧名"))
        if NEW in seq:
            hit.append((str(L.get("id")), "新名"))
    print("  线路站序里出现的记录（线号, 用的哪个名）：%s" % hit)
    nkeys = [k for k in st if A in k or NEW in k]
    print("  stations 里名字相关的键：%s" % nkeys)

    print()
    print("=" * 72)
    print("C  改了文字【不点保存】就关窗口")
    print("=" * 72)
    ip.show_station(B)
    pump(6)
    ip._widgets["station_name"].setText(B + "改了不保存")
    pump(4)
    typed = ip._widgets["station_name"].text()
    print("  输入框改成：%r（不点保存，直接关窗口）" % typed)
    win.close()
    pump(10)
    st2, _ = snap_json()
    print("  关窗口后 JSON 里 %r 的 station_name = %r" % (B, st2.get(B, {}).get("station_name")))
    print("  → 结论：%s" % ("★ 改动丢了（关窗口只写内存里已提交的数据，编辑框里的没提交）"
                            if st2.get(B, {}).get("station_name") != typed
                            else "改动被保存了"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
