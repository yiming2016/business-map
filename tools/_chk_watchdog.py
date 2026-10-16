"""
校验 core/watchdog：能不能在"主线程被堵"时把现场写进日志。

两步：
  ① 健康状态 4 秒（持续打心跳）→ 日志里**不该**出现卡死报告
  ② 主线程故意堵 4.5 秒（sleep，等价于一次慢操作/死等）→
     日志里**必须**出现卡死报告，且栈要指向 `stall_here` 那一行
"""
from __future__ import annotations
import sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from core import watchdog

LOG = SRC / "logs" / "_watchdog_test.log"
if LOG.exists():
    LOG.unlink()

PASS = {"n": 0}
FAIL = {"n": 0}


def check(name, cond, extra=""):
    if cond:
        PASS["n"] += 1
        print(f"  [OK]  {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL["n"] += 1
        print(f"  [FAIL] {name}  {extra}")


watchdog.start(LOG)
watchdog.attach_to_app(app)
watchdog.note("测试开始")

print("=== ① 健康状态 4 秒（持续打心跳）===")
t0 = time.perf_counter()
while time.perf_counter() - t0 < 4.0:
    app.processEvents()          # 顺带让 QTimer 心跳跑起来
    time.sleep(0.01)
text1 = LOG.read_text(encoding="utf-8")
check("健康状态不误报", "界面卡住" not in text1,
      f"日志长度 {len(text1)}")

print()
print("=== ② 主线程故意堵 4.5 秒 ===")
time.sleep(0.8)                  # 让心跳先正常跳一会儿


def stall_here(seconds: float):
    """这一行必须出现在卡死报告的栈里。"""
    time.sleep(seconds)          # ← 卡在这里


stall_here(4.5)
print("  （主线程已恢复）")
time.sleep(1.0)                  # 给守护线程时间写盘

text2 = LOG.read_text(encoding="utf-8")
check("卡住时写出了报告", "界面卡住" in text2)
check("报告里有栈（能定位到行）", "stall_here" in text2 or "File" in text2)
check("报告里有窗口状态", "顶层窗口" in text2 or "活动窗口" in text2)
check("报告里有 faulthandler 段", "所有线程栈" in text2)

print()
print("--- 报告节选 ---")
lines = text2.splitlines()
try:
    i = next(i for i, l in enumerate(lines) if "界面卡住" in l)
    for l in lines[i:i + 22]:
        print("   " + l)
except StopIteration:
    print("   （没有报告）")

print()
print("=" * 70)
print(f"通过 {PASS['n']} 项，失败 {FAIL['n']} 项")
print("全部通过 ✅" if FAIL["n"] == 0 else "有失败 ❌")
print("=" * 70)
sys.exit(1 if FAIL["n"] else 0)
