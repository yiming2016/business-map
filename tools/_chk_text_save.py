# -*- coding: utf-8 -*-
"""回归：「文字改了之后不被保存」（用户原话「修复文字修改为之后可能不被保存的问题」）

实测出来的三条丢数据的路（v2.6.57 前）：
  A 面板里改了字**不点保存**就点地图上别的站 ⇒ `show_station()` 直接重建表单 ⇒ 静默丢弃
  C 面板里改了字**不点保存**就关窗口       ⇒ `closeEvent` 只写内存里已提交的数据 ⇒ 同样丢弃
  B 改**站名**点了保存 ⇒ stations 的键仍是旧名、线路站序也是旧名（半保存，另案）

修法：`InfoPanel.flush_pending()` —— 切走 / 关窗口前先把"改了没保存"的内容提交掉，
并在状态栏明说一声（自动保存如果一点动静都没有，用户还是会怀疑存没存）。

★ 反面判据同样重要（A3）：**没有改动时不许乱存**。空值口径没做等价（None vs ""）
会让 370 个站"全脏" ⇒ 每次切站都自动保存一次，撤销栈被灌满、还平白写盘。

用法：
    python tools/_chk_text_save.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402


def _tmp_dir():
    t = Path(tempfile.mkdtemp(prefix="chktext_"))
    for n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json"):
        if (CDM.DATA_DIR / n).exists():
            shutil.copy(CDM.DATA_DIR / n, t / n)
    (t / "covers").mkdir(exist_ok=True)
    return t


_TMP = _tmp_dir()
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402

A, B = "车公庙", "老街"
FIELD = "description"   # ★ 用"简介"而不是"站点名称"：站名是主键，改它会走改名换键的流程
                        #   （那是 _chk_rename_station 的地盘），这里要测的是"改了不保存"
NEW = "【测试】这是一段改过的简介文字"
PY = sys.executable
TAG = "##TEXTCHK##"


def pump(n=8):
    for _ in range(n):
        QTest.qWait(10)
        QApplication.processEvents()


def _all():
    return json.loads((_TMP / "stations.json").read_text(encoding="utf-8"))["stations"]


def st_get(sid):
    return _all().get(sid)


def json_name(sid):
    return (st_get(sid) or {}).get("station_name")


def json_field(sid):
    return (st_get(sid) or {}).get(FIELD)


def set_field(ip, val):
    """「简介」是多行框（QPlainTextEdit），没有 setText，统一在这里挑对的入口"""
    w = ip._widgets[FIELD]
    if hasattr(w, "setPlainText"):
        w.setPlainText(val)
    else:
        w.setText(val)


def probe(what):
    """子进程模式：只跑某一项并打印一行结论（供变异自检对比）"""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    ip = win.info_panel
    ip.show_station(A)
    pump(6)
    set_field(ip, NEW)
    pump(4)
    ip.show_station(B)          # ← 不点保存就切走
    pump(8)
    got = json_field(A)
    win.close()
    print("%s %s" % (TAG, json.dumps({"cut": got})))
    return 0


def main():
    if "--probe" in sys.argv:
        return probe(sys.argv[-1])
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(12)
    ip = win.info_panel
    dm = CDM.get_data_manager()
    ok = bad = 0

    def chk(name, cond, detail):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  [OK]   %s\n         %s" % (name, detail))
        else:
            bad += 1
            print("  [FAIL] %s\n         %s" % (name, detail))

    # ---- A1 不点保存就切站 ----
    ip.show_station(A)
    pump(6)
    ORIG = json_field(A)          # 改之前的原值（撤销后应该回到它）
    set_field(ip, NEW)
    pump(4)
    ip.show_station(B)
    pump(8)
    got = json_field(A)
    chk("A1 改了字不点保存就切站 ⇒ 改动还在", got == NEW,
        "JSON 里「%s」的 %s = %r（期望 %r）" % (A, FIELD, got, NEW))

    # ---- A5 自动保存也能 Ctrl+Z 撤回来 ----
    win._on_undo()
    pump(8)
    back = json_field(A)
    chk("A5 自动保存的内容 Ctrl+Z 能撤回来", back == ORIG,
        "撤销后 %s = %r（期望改前的 %r）" % (FIELD, back, ORIG))

    # ---- A3 反面：没改动时不许写盘 ----
    calls = []
    _orig = dm.save

    def counted(*a, **k):
        calls.append(1)
        return _orig(*a, **k)
    dm.save = counted
    seq = [A, B, A, B, "福田", "老街", A, B]
    for s in seq:
        ip.show_station(s)
        pump(3)
    n_calls = len(calls)
    dm.save = _orig
    chk("A3 没改动时切站**不许**写盘", n_calls == 0,
        "连切 %d 次站，落盘 %d 次（应为 0 —— 否则撤销栈会被灌满）"
        % (len(seq), n_calls))

    # ---- A4 站名清空不许存出没名字的站 ----
    ip.show_station(A)
    pump(6)
    ip._widgets["station_name"].setText("")
    pump(4)
    ip.show_station(B)
    pump(8)
    empty = json_name(A)
    chk("A4 站名清空后切站 ⇒ 不许存出没名字的站", bool(empty),
        "JSON 里 station_name = %r（不能是空）" % empty)

    # ---- A2 不点保存就关窗口（放最后，关了就没了）----
    ip.show_station(B)
    pump(6)
    set_field(ip, B + "关窗口前改的")
    pump(4)
    win.close()
    pump(10)
    got2 = json_field(B)
    chk("A2 改了字不点保存就关窗口 ⇒ 改动还在",
        got2 == B + "关窗口前改的",
        "关窗口后 JSON 里 %s = %r" % (FIELD, got2))

    # ---- B 变异自检 ----
    print("-" * 66)
    env = dict(os.environ)
    env["METROEDITOR_NO_AUTOSAVE"] = "1"
    r = subprocess.run([PY, str(Path(__file__).resolve()), "--probe", "cut"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    m2 = None
    for line in (r.stdout or "").splitlines():
        if TAG in line:
            m2 = json.loads(line.split(TAG, 1)[1].strip())
    if m2 is None:
        chk("B 变异自检（关掉自动兜底）", False,
            "子进程没给出结论：%s" % ((r.stderr or "")[-300:]))
    else:
        chk("B 变异（NO_AUTOSAVE=1）必须把 A1 打回丢失",
            m2["cut"] != NEW,
            "变异后切站，%s = %r（期望退回改前的 %r，即改动丢失才对）"
            % (FIELD, m2["cut"], ORIG))
    print("-" * 66)
    print("通过 %d / 失败 %d" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
