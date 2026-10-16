"""
main.py
========================
程序入口。
"""

import sys
import os
import time
import traceback
from pathlib import Path

# 让 PyInstaller 打包后能找到模块路径
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ★ 打包成 windowed exe 后没有控制台，异常会被静默吞掉 —— 任何一个小错误
#   都会伪装成"玄学 bug"（如白屏、错位）。把所有未捕获异常写入日志文件。
APP_VERSION = "v2.7.33"


def _setup_error_log():
    # PyInstaller onefile 下 __file__ 在临时解包目录，日志要写到 exe 旁边
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent   # 打包后 = 软件/
    else:
        app_dir = PROJECT_ROOT                            # 源码运行 = 源码/
    # ★ 日志跟着程序走（不是"上一级"）：
    #   打包后 → 软件/logs（和 exe、data 放一起，工程根目录不再多出 logs/）
    #   开发时 → 源码/logs
    log_dir = app_dir / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
    except Exception:
        log_dir = Path(os.environ.get("TEMP", "."))
    log_file = log_dir / "error.log"

    def _log(msg: str):
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

    _log(f"\n==== 启动 {APP_VERSION} build={time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")

    def _excepthook(t, v, tb):
        _log(f"[{time.strftime('%H:%M:%S')}] 未捕获异常 {t.__name__}: {v}\n"
             + "".join(traceback.format_exception(t, v, tb)))

    sys.excepthook = _excepthook
    try:
        sys.stderr = _LogTee(sys.stderr, _log)
    except Exception:
        pass
    return log_file


class _LogTee:
    """把 stderr 写入同时转发到原目标（打包后 stderr 通常是 None）。"""

    def __init__(self, original, log):
        self.original = original
        self.log = log
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.log(f"[{time.strftime('%H:%M:%S')}] {line}\n")
        if self.original:
            try:
                self.original.write(s)
            except Exception:
                pass

    def flush(self):
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass


def main():
    log_file = _setup_error_log()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QIcon
    from ui.main_window import MainWindow

    # ★ v2.4.19：卡死看门狗。
    #   界面一旦「未响应」（主线程被堵 ≥3 秒），就把"卡在哪一行 +
    #   当时所有窗口的可见性/位置"写进 logs/error.log。
    #   这类问题在别人机器上常复现不出来，没有它就只能干瞪眼。
    from core import watchdog
    watchdog.start(log_file)

    # ★ v2.6.50：自动打开（回归脚本 / 打包后拉起）时**不抢焦点**。
    #   ★★ 两条"传参"的路都实测失败过，别再试：
    #     - Popen(env=...) 注入环境变量 → explorer.exe 用**它自己**的环境启动目标进程，
    #       环境变量根本传不进去（v2.6.45 那版因此形同虚设）；
    #     - explorer.exe <exe> --noactivate → explorer 只接受**路径**参数，多出来的参数
    #       会让目标 exe 压根起不来（v2.6.49 那版：日志里连启动行都没有）。
    #   ⇒ 最终落到**标记文件**：启动脚本在 exe 同目录放 `.noactivate`，
    #     本进程启动时"读到即删"并置位。命令行参数仍保留作第二通道（万一以后不用 explorer）。
    _flag = os.path.join(os.path.dirname(sys.executable or ""), ".noactivate")
    if os.path.isfile(_flag):
        os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
        try:
            os.remove(_flag)        # 读到即删：不影响用户以后手动双击
        except Exception:
            pass
    if "--noactivate" in sys.argv:
        os.environ["METROEDITOR_NO_ACTIVATE"] = "1"

    app = QApplication(sys.argv)
    watchdog.attach_to_app(app)

    # 全局字体：★ 加粗（主界面所有文字）
    font = QFont("Microsoft YaHei", 10)
    font.setBold(True)
    font.setWeight(QFont.Bold)
    app.setFont(font)

    win = MainWindow()
    win.setWindowTitle(f"深圳地铁编辑器 {APP_VERSION}")
    # ★ v2.7.0：软件 logo（深圳地铁图标）—— 标题栏 / 任务栏 / Alt-Tab 都用它。
    #   打包后走 sys._MEIPASS/assets/logo.png（build_exe.py 已 --add-data）；
    #   开发时走 源码/assets/logo.png。设置失败绝不影响启动。
    try:
        from core.data_manager import _frozen_assets_dir
        _logo = Path(_frozen_assets_dir()) / "logo.png"
        if _logo.is_file():
            _ic = QIcon(str(_logo))
            app.setWindowIcon(_ic)
            win.setWindowIcon(_ic)
        else:
            print("[logo] 未找到图标文件：", _logo)
    except Exception as _e:
        print("[logo] 设置失败：", repr(_e))
    win.show()
    # ★ 双保险：Qt 的 WA_ShowWithoutActivating 之外，再让 Win32 明确"显示但不激活"
    if os.environ.get("METROEDITOR_NO_ACTIVATE") == "1":
        try:
            import ctypes
            hwnd = int(win.winId())
            ctypes.windll.user32.ShowWindow(hwnd, 4)          # SW_SHOWNOACTIVATE
            # SWP: NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|SHOWWINDOW —— 不改位置不改层级，只是不激活
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                              0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0040)
        except Exception as e:      # 失败也不许影响启动
            print("[noactivate] 调用失败：", repr(e))
    watchdog.note(f"主窗口已显示 {win.width()}x{win.height()}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
