# -*- coding: utf-8 -*-
"""_chk_exit_ask_gui.py — v2.7.32 回归（真窗口路径）：关窗时的"要不要保存为图片"到底弹不弹

和 `_chk_exit_ask.py`（纯逻辑）的分工：这份**真的构造 MainWindow、真的调 closeEvent**，
把 QMessageBox.question 换成一个计数器，看它在四种场景下各被调用几次。

背景（用户反馈）：
  开一下软件、**一个元素都没改**、关掉时也被问「要不要把整张图保存为图片？」。
期望：
  A 数据没变 + png 已是最新        → **不问**
  B 改了站点数据、图已过期          → 问（且先落盘再问）
  C 设置里关掉「退出前询问」        → 不问
  D 本次根本没烘过图               → 不问（保持原行为）
  E 数据没变但 png 被删了          → 问（图不在了，提醒一下）
  --mutate-old：把 closeEvent 的判断改回 v2.7.31 的旧写法（只看有没有图）
                → A 应当**失败**（证明本回归抓得住这个 bug）

★ 绝不弹窗打扰用户：脚本自己先把平台设成 offscreen；测试数据全部在临时目录。
运行：
    "C:/Users/29773/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/_chk_exit_ask_gui.py
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

# ★ 必须在 import PySide6 之前设：离屏渲染，屏幕上不会闪窗口
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_VIEW_START"] = "1"      # 不自动进看图模式（省几秒烘图）

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QCloseEvent                 # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ui import image_mode as IM                       # noqa: E402
from ui.main_window import MainWindow                 # noqa: E402

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s   %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (name, detail))


class StubDM:
    """替身 DataManager：只记 save() 有没有被调用，绝不写真实数据。"""

    def __init__(self, data_dir):
        self.DATA_DIR = str(data_dir)
        self.saved = 0

    def save(self):
        self.saved += 1


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 800)

    work = Path(tempfile.mkdtemp(prefix="chk_exit_ask_gui_"))
    try:
        for name in ("stations.json", "lines.json"):
            s = ROOT / "data" / name
            (work / name).write_text(s.read_text(encoding="utf-8") if s.exists() else "{}",
                                     encoding="utf-8")

        stub = StubDM(work)
        win.dm = stub                       # 落盘目标换成替身（不写真实数据）
        ok("落盘目标已换成临时目录", str(work) in win._data_dir())

        sec = IM.load_settings(str(work))
        png = Path(IM.png_path(str(work), sec))
        png.parent.mkdir(parents=True, exist_ok=True)

        # 把弹窗换成计数器。
        # ★ 注意：不要去给 QMessageBox 这个 C++ 类挂属性（PySide6 会报
        #   "cannot set attribute"）。main_window 里是**调用时**才
        #   `from PySide6.QtWidgets import QMessageBox`，所以直接换掉模块里这个名字最稳。
        import PySide6.QtWidgets as QW
        asked = {"n": 0}

        class FakeQMB:
            Yes = 1
            No = 0

            @staticmethod
            def question(*a, **kw):
                asked["n"] += 1
                return FakeQMB.No

        QW.QMessageBox = FakeQMB

        if os.environ.get("CHK_MUTATE_OLD") == "1":
            def old_close(self, event):
                try:
                    self.dm.save()
                except Exception:
                    pass
                try:
                    s2 = self._img_settings()
                    if s2.get("ask_on_exit", True) and getattr(self, "_view_img", None) is not None:
                        import PySide6.QtWidgets as QW2
                        QW2.QMessageBox.question(self, "退出", "旧写法（只看有没有烘过图）",
                                                 QW2.QMessageBox.Yes | QW2.QMessageBox.No)
                except Exception:
                    pass
                QApplication.processEvents()
            MainWindow.closeEvent = old_close
            print("  （变异模式：closeEvent 已换回 v2.7.31 旧写法）")

        def close_once():
            asked["n"] = 0
            stub.saved = 0
            win.closeEvent(QCloseEvent())
            app.processEvents()
            return asked["n"], stub.saved

        print("--- A 数据没变 + png 已是最新 → 不该问 ---")
        png.write_bytes(b"fake-png")
        win._view_img = object()
        win._img_sig_done = IM.signature(str(work))
        n, saved = close_once()
        ok("没有弹询问框", n == 0, "asked=%d" % n)
        ok("关窗前仍然先落盘（dm.save 被调用）", saved == 1, "saved=%d" % saved)
        ok("png 没被改写", png.read_bytes() == b"fake-png")

        print("--- B 改了站点数据、图过期 → 要问 ---")
        st = json.loads((work / "stations.json").read_text(encoding="utf-8"))
        if isinstance(st, dict):
            st["__chk__"] = {"name": "回归测试站"}
        else:
            st = list(st) + [{"id": "__chk__", "name": "回归测试站"}]
        (work / "stations.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        n, saved = close_once()
        ok("弹了询问框", n == 1, "asked=%d" % n)
        ok("先落盘再问", saved == 1, "saved=%d" % saved)

        print("--- C 设置里关掉「退出前询问」 → 不问 ---")
        sec2 = dict(sec)
        sec2["ask_on_exit"] = False
        IM.save_settings(str(work), sec2)
        n, _ = close_once()
        ok("关了开关就不再问", n == 0, "asked=%d" % n)
        IM.save_settings(str(work), sec)

        print("--- D 本次没烘过图 → 不问（保持原行为）---")
        win._view_img = None
        n, _ = close_once()
        ok("没烘过图不问", n == 0, "asked=%d" % n)

        print("--- E 数据没变但 png 被删了 → 问 ---")
        win._view_img = object()
        win._img_sig_done = IM.signature(str(work))
        png.unlink()
        n, _ = close_once()
        ok("png 不在 → 提醒一下", n == 1, "asked=%d" % n)

    finally:
        try:
            win.deleteLater()
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)

    print("\n== _chk_exit_ask_gui 结果：%d 通过 / %d 失败 ==" % (PASS, FAIL))
    if os.environ.get("CHK_MUTATE_OLD") == "1":
        print("（变异模式：只要 A 的“没有弹询问框”是 FAIL，就说明本回归有效）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
