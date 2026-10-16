"""
用 QInputMethodEvent 模拟**真实中文输入法**输入（预编辑 + 上屏），
逐个控件测耗时；看门狗改为在事件循环里心跳（避免上次的假阳性）。

对照：
  · 预编辑（拼音串，还没选字）→ QInputMethodEvent("ce shi", [])
  · 上屏（选定汉字）        → QInputMethodEvent("测试", [])   ← commit
"""
from __future__ import annotations
import sys, time, threading
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

HEART = {"t": time.perf_counter()}
STALL = {"v": 0.0}


def watchdog():
    while True:
        dt = time.perf_counter() - HEART["t"]
        if dt > STALL["v"]:
            STALL["v"] = dt
        time.sleep(0.02)


threading.Thread(target=watchdog, daemon=True).start()


def pump(ms=150):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        HEART["t"] = time.perf_counter()      # ★ 事件循环里也心跳
        app.processEvents()
        time.sleep(0.002)


def ime_preedit(w, text: str) -> None:
    """预编辑（输入法还没选字，屏幕上显示拼音下划线）"""
    w.inputMethodEvent(QInputMethodEvent(text, []))


def ime_commit(w, text: str) -> None:
    """上屏（选定汉字，真正进入输入框）"""
    w.inputMethodEvent(QInputMethodEvent(text, []))


def ime_type(w, pinyin: str, hanzi: str) -> None:
    """完整一轮：敲拼音 → 选字上屏"""
    w.inputMethodEvent(QInputMethodEvent(pinyin, []))
    app.processEvents()
    w.inputMethodEvent(QInputMethodEvent(hanzi, []))
    app.processEvents()


def timed(label, fn, limit=1000.0):
    HEART["t"] = time.perf_counter()
    t0 = time.perf_counter()
    fn()
    pump(80)
    ms = (time.perf_counter() - t0) * 1000.0
    flag = "🔴 卡死!" if ms > limit else ("🟡 慢" if ms > 200 else "  ok")
    print(f"  {flag} {label:<40} {ms:8.1f} ms", flush=True)
    return ms


print("=" * 100)
print("① 裸控件：QLineEdit 用输入法事件打中文（对照 QTest 会崩）")
print("=" * 100)
le = QLineEdit(); le.show(); pump(300)
timed("裸 QLineEdit 预编辑+上屏 '测试'", lambda: ime_type(le, "ceshi", "测试"))
print(f"     结果文本 = {le.text()!r}")
le.close()

print()
print("=" * 100)
print("② 真实 MainWindow → 面板：各字段用输入法打中文")
print("=" * 100)
win = MainWindow(); win.resize(1480, 900); win.show(); pump(700)
sid = list(get_data_manager().all_stations().keys())[0]
win._on_station_clicked(sid); pump(400)
panel = win.info_panel
print(f"  面板站点 = {panel.current_station_id()}")

worst = (0.0, "")
for key in ("station_name", "open_date"):
    w = panel._widgets.get(key)
    if not isinstance(w, QLineEdit):
        continue
    w.setFocus(); w.clear(); pump(60)
    for i in range(8):
        ms = timed(f"面板 {key} 第{i+1}次输入法打中文",
                   lambda w=w, i=i: ime_type(w, f"ceshi{i}", "测试"))
        if ms > worst[0]:
            worst = (ms, f"面板 {key}")
    print(f"     文本 = {w.text()!r}")

for key in ("description", "exits", "facilities", "landmarks", "notes"):
    w = panel._widgets.get(key)
    if not isinstance(w, QPlainTextEdit):
        continue
    w.setFocus(); w.clear(); pump(60)
    ms = timed(f"面板 {key} 输入法打一段中文",
               lambda w=w: ime_type(w, "zhe shi yi duan", "这是一段测试文字"))
    if ms > worst[0]:
        worst = (ms, f"面板 {key}")

print()
print("=" * 100)
print("③ 工具栏搜索框 输入法打中文")
print("=" * 100)
sb = win.search_box
sb.setFocus(); pump(60)
timed("搜索框 输入法打中文", lambda: ime_type(sb, "jichangdong", "机场东"))

print()
print("=" * 100)
print("④ EditDialog（无边框 + SetWindowRgn）里输入法打中文")
print("=" * 100)
dlg = EditDialog(station_id=sid, parent=win)
dlg.show(); pump(700)
for key in ("station_name", "description", "open_date", "exits", "notes"):
    w = dlg._widgets.get(key)
    if not isinstance(w, (QLineEdit, QPlainTextEdit)):
        continue
    w.setFocus(); pump(60)
    ms = timed(f"弹窗 {key} 输入法打中文",
               lambda w=w: ime_type(w, "ceshi", "测试"))
    if ms > worst[0]:
        worst = (ms, f"弹窗 {key}")

print()
print("=" * 100)
print("⑤ 连续 40 轮输入法（模拟快速打字）")
print("=" * 100)
w = dlg._widgets.get("open_date")
w.setFocus(); w.clear()
HEART["t"] = time.perf_counter()
t0 = time.perf_counter()
for i in range(40):
    w.inputMethodEvent(QInputMethodEvent(f"py{i}", []))
    app.processEvents()
    w.inputMethodEvent(QInputMethodEvent("字", []))
    app.processEvents()
    HEART["t"] = time.perf_counter()
print(f"  40 轮共 {(time.perf_counter()-t0)*1000:.1f} ms  "
      f"（平均 {(time.perf_counter()-t0)*1000/40:.1f} ms/轮）  文本长度={len(w.text())}")

print()
print("=" * 100)
print(f"最慢一步：{worst[1]}  {worst[0]:.1f} ms")
print(f"全程最长停顿（看门狗）= {STALL['v']*1000:.0f} ms")
print("=" * 100)

dlg.close(); win.close()
print("[DONE]")
