"""
core/watchdog.py
========================
界面卡死看门狗。

为什么需要它：
  「未响应」这类问题在开发机上常常**复现不出来** —— 一旦卡住，
  用户只能看到窗口标题变成「(未响应)」，没有任何线索。
  有了这个看门狗，只要**卡住一次**，日志里就会留下：
    · 主线程当时卡在哪一行 Python 代码（栈）
    · 所有顶层窗口的可见性 / 位置 / 标题
    · 当前弹窗、模态窗口、焦点控件是谁
  —— 足以定位"是死循环、是慢操作、还是有窗口被藏在后面"。

设计要点：
  · 心跳由主线程里的 QTimer 打（见 `attach_to_app`）。
    主线程一旦被堵住，心跳就停 —— 正是我们要检测的。
  · ★ 注意：`dlg.exec()` 这种**嵌套事件循环**里 QTimer 照常触发，
    所以"弹窗开着"不会被误判成卡死。
  · 双路取证：
      ① `sys._current_frames()` 拿 Python 栈（好读，能定位到 .py 行号）
      ② `faulthandler.dump_traceback_later()` 兜底
         —— 万一主线程卡在 C 层不释放 GIL，① 拿不到，② 仍能出栈
  · 只在**卡住的那一刻**取证，且每次阻塞只报一次，不刷屏。
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

# 判定阈值（秒）。Windows 自己大约 5 秒才标「未响应」，我们提前一点。
STALL_SECONDS = 3.0
# 主线程心跳的间隔（由 QTimer 驱动）
BEAT_MS = 200

_lock = threading.Lock()
_hb = time.perf_counter()
_started = False
_log_fh = None            # 保持打开，faulthandler 要用它的 fileno
_main_tid: Optional[int] = None
_reported = False         # 当前这次阻塞是否已经报过


# ------------------------------------------------------------
# 写日志
# ------------------------------------------------------------
def _write(text: str) -> None:
    fh = _log_fh
    if fh is None:
        return
    try:
        with _lock:
            fh.write(text)
            fh.flush()
    except Exception:
        pass


def note(msg: str) -> None:
    """记一条界面事件（开弹窗 / 关弹窗 / 保存…），给卡死现场留面包屑。"""
    _write(f"[{time.strftime('%H:%M:%S')}] [UI] {msg}\n")


# ------------------------------------------------------------
# 心跳
# ------------------------------------------------------------
def beat() -> None:
    """主线程活着就打一下。由 QTimer 调用。"""
    global _hb, _reported
    _hb = time.perf_counter()
    _reported = False


# ------------------------------------------------------------
# 重活豁免
# ------------------------------------------------------------
_hold_until = 0.0


def hold(seconds: float, reason: str = "") -> None:
    """★ v2.7.17：接下来 N 秒内主线程不动也**不要报警**。

    用途：烘整张大图 + 存 png 这种**已知要几秒**的重活（实测 3.1s，
    栈明确停在 `save_png`）。没有它，每次首次出图都会在日志里留一条
    「界面卡住 3.1 秒」的**假报告**，把以后真卡死的线索淹掉。
    """
    global _hold_until
    _hold_until = max(_hold_until, time.perf_counter() + float(seconds))
    note(f"重活豁免 {seconds:.0f}s：{reason}")


# ------------------------------------------------------------
# 现场取证
# ------------------------------------------------------------
def _qt_state() -> str:
    """把 Qt 的窗口状态写出来 —— 藏着没显示的模态窗口一眼就能看见。"""
    out = []
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return "    [UI] QApplication 实例不存在\n"

        def nm(w):
            return type(w).__name__ if w is not None else "None"

        out.append(f"    活动窗口={nm(app.activeWindow())}  "
                   f"活动弹窗={nm(app.activePopupWidget())}  "
                   f"模态窗口={nm(app.activeModalWidget())}  "
                   f"焦点控件={nm(app.focusWidget())}\n")
        for w in app.topLevelWidgets():
            try:
                g = w.geometry()
                out.append(f"    顶层窗口 {nm(w):<14} visible={int(w.isVisible())} "
                           f"active={int(w.isActiveWindow())} "
                           f"geom=({g.x()},{g.y()},{g.width()}x{g.height()}) "
                           f"title={w.windowTitle()!r}\n")
            except Exception:
                pass
    except Exception as e:
        out.append(f"    [UI] 状态获取失败：{e}\n")
    return "".join(out)


def _dump_once(elapsed: float) -> None:
    _write(f"\n[{time.strftime('%H:%M:%S')}] "
           f"!!!!!! 界面卡住 {elapsed:.1f} 秒 !!!!!!\n")
    _write("---- 所有线程栈（faulthandler，C 层卡住也能出）----\n")
    try:
        # 同步转储：立刻写进日志，顺序才跟上面的标题对得上。
        # （用 dump_traceback_later 是异步的，栈会飘到"报告结束"后面去，难读。）
        faulthandler.dump_traceback(file=_log_fh, all_threads=True)
    except Exception as e:
        _write(f"    faulthandler 转储失败：{e}\n")

    _write("---- 主线程 Python 栈（能拿到时最直观）----\n")
    try:
        frames = sys._current_frames()
        fr = frames.get(_main_tid) if _main_tid else None
        if fr is not None:
            _write("".join(traceback.format_stack(fr)))
        else:
            _write("    拿不到主线程栈（可能卡在 C 层且未释放 GIL）\n")
    except Exception as e:
        _write(f"    取栈失败：{e}\n")

    _write("---- 当时的窗口状态 ----\n")
    _write(_qt_state())
    _write("!!!!!! 卡死报告结束 !!!!!!\n\n")


# ------------------------------------------------------------
# 守护线程
# ------------------------------------------------------------
def _loop() -> None:
    global _reported
    while True:
        time.sleep(0.5)
        dt = time.perf_counter() - _hb
        if dt >= STALL_SECONDS:
            # ★ v2.7.17：正在干已知的重活（烘图 / 存大图）⇒ 不算卡死
            if time.perf_counter() < _hold_until:
                continue
            with _lock:
                if _reported:
                    continue
                _reported = True
            _dump_once(dt)


# ------------------------------------------------------------
# 启动 / 接管
# ------------------------------------------------------------
def start(log_path: Path, stall_seconds: float = STALL_SECONDS) -> None:
    """启动看门狗。log_path 通常是 logs/error.log。"""
    global _started, _log_fh, _main_tid, _hb
    if _started:
        return
    _started = True
    _main_tid = threading.main_thread().ident
    _hb = time.perf_counter()

    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        # 行缓冲：卡死时进程可能被强杀，缓冲内容会丢
        _log_fh = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return

    try:
        faulthandler.enable(file=_log_fh, all_threads=True)
    except Exception:
        pass

    note(f"看门狗已启动（阈值 {stall_seconds:.0f}s）")
    threading.Thread(target=_loop, name="freeze-watchdog", daemon=True).start()


def attach_to_app(app) -> None:
    """把心跳挂到 Qt 事件循环上。必须在 QApplication 建好之后调用。"""
    from PySide6.QtCore import QTimer
    t = QTimer(app)
    t.setInterval(BEAT_MS)
    t.timeout.connect(beat)
    t.start()
    app._freeze_watchdog_timer = t        # 防被 GC
