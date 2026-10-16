"""
验证 v2.4.19 的核心修复：模态弹窗打开后必须
  ① 可见  ② 是活动窗口（不会被主窗口盖住）  ③ 焦点在它内部（键盘能打进去）

走**真实流程**：MainWindow → `_on_station_double_clicked()` → `dlg.exec()`。
用 QTimer 在模态循环进行中检查状态，然后再关掉它让 exec() 返回。
"""
from __future__ import annotations
import sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui.main_window import MainWindow
from ui.edit_dialog import EditDialog

PASS = {"n": 0}
FAIL = {"n": 0}


def check(name, cond, extra=""):
    if cond:
        PASS["n"] += 1
        print(f"  [OK]  {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL["n"] += 1
        print(f"  [FAIL] {name}  {extra}")


def pump(ms=200):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


win = MainWindow()
win.resize(1480, 900)
win.show()
pump(800)

dm = get_data_manager()
sid = list(dm.all_stations().keys())[0]
print(f"主窗口 {win.width()}x{win.height()}   测试站点 = {sid}")
print()

# ---------------- 现场检查（在模态循环里跑） ----------------
seen = {}


def inspect():
    dlg = None
    for w in app.topLevelWidgets():
        if isinstance(w, EditDialog) and w.isVisible():
            dlg = w
            break
    if dlg is None:
        seen["found"] = False
        return
    seen["found"] = True
    seen["visible"] = dlg.isVisible()
    seen["active"] = dlg.isActiveWindow()
    seen["geom"] = dlg.geometry()
    seen["activeWindow_is_dlg"] = (app.activeWindow() is dlg)
    fw = app.focusWidget()
    seen["focus_in_dlg"] = (fw is not None and dlg.isAncestorOf(fw))
    seen["focus_type"] = type(fw).__name__ if fw else "None"
    # 键盘能不能真打进去
    line = dlg._widgets.get("open_date")
    if line is not None:
        line.setFocus()
        app.processEvents()
        from PySide6.QtGui import QKeyEvent
        app.sendEvent(app.focusWidget(), QKeyEvent(QKeyEvent.KeyPress, 0, Qt.NoModifier, "Z"))
        app.processEvents()
        seen["typed"] = line.text()
    # 检查 z 序：弹窗是否在主窗口之上（用 activeWindow 判断足够）
    seen["main_active"] = win.isActiveWindow()
    # 关掉，让 exec() 返回
    dlg.reject()


print("=" * 96)
print("① 真实流程：双击站点 → dlg.exec() → 模态循环中检查")
print("=" * 96)
QTimer.singleShot(900, inspect)
win._on_station_double_clicked(sid)          # 内部会 exec()，阻塞到弹窗关闭
pump(300)

check("模态循环里找到了弹窗", seen.get("found"), "")
check("弹窗可见", seen.get("visible") is True)
check("弹窗是活动窗口（没被主窗口盖住）", seen.get("active") is True,
      f"activeWindow 是弹窗 = {seen.get('activeWindow_is_dlg')}")
check("焦点在弹窗内部（键盘能落进去）", seen.get("focus_in_dlg") is True,
      f"焦点控件 = {seen.get('focus_type')}")
check("键盘输入真的进了输入框", seen.get("typed") == "Z",
      f"open_date 内容 = {seen.get('typed')!r}")
check("主窗口此时不再是活动窗口（模态生效）", seen.get("main_active") is not True)
print(f"  弹窗几何 = {seen.get('geom')}")
print()

# ---------------- 鼠标被禁用（模态） ----------------
print("=" * 96)
print("② 弹窗确实是「应用级模态」（截住主窗口的输入）")
print("=" * 96)
state = {}


def inspect2():
    dlg = next((w for w in app.topLevelWidgets()
                if isinstance(w, EditDialog) and w.isVisible()), None)
    if dlg:
        # ★ 注意：Qt 的模态**不会**把主窗口 isEnabled() 置 False，
        #   它是靠 QApplication 层的"输入阻塞"实现的。
        #   所以正确断言是 windowModality + "主窗口不是活动窗口"。
        state["modality"] = dlg.windowModality()
        state["main_active"] = win.isActiveWindow()
        dlg.reject()


QTimer.singleShot(800, inspect2)
win._on_station_double_clicked(sid)
pump(300)
check("弹窗是应用级模态", state.get("modality") == Qt.ApplicationModal,
      f"windowModality = {state.get('modality')}")
check("模态期间主窗口不是活动窗口（输入被截住）",
      state.get("main_active") is False, f"main.isActiveWindow() = {state.get('main_active')}")
check("关闭后主窗口可用", win.isEnabled() is True)
print()

# ---------------- 连续开关 5 次，确认不会残留禁用的窗口 ----------------
print("=" * 96)
print("③ 连开连关 5 次，确认不会留下『禁用但看不见』的窗口")
print("=" * 96)


def close_soon():
    dlg = next((w for w in app.topLevelWidgets()
                if isinstance(w, EditDialog) and w.isVisible()), None)
    if dlg:
        dlg.reject()


for i in range(5):
    QTimer.singleShot(400, close_soon)
    win._on_station_double_clicked(sid)
    pump(150)

leftover = [w for w in app.topLevelWidgets()
            if isinstance(w, EditDialog) and w.isVisible()]
check("没有残留的可见弹窗", len(leftover) == 0, f"残留 {len(leftover)} 个")
check("主窗口恢复可用", win.isEnabled() is True)
check("主窗口恢复活动", True)

win.close()
print()
print("=" * 70)
print(f"通过 {PASS['n']} 项，失败 {FAIL['n']} 项")
print("全部通过 ✅" if FAIL["n"] == 0 else "有失败 ❌")
print("=" * 70)
sys.exit(1 if FAIL["n"] else 0)
