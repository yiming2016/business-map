# -*- coding: utf-8 -*-
"""_chk_view_mode_conflicts.py — v2.7.33 回归：看图模式那一圈的四个"状态打架"

背景（一轮全项目审计查出来的，都是真会咬人的）：
  ① `ui/map_view.py:_save_view_settings()` 把整个 `view_settings.json` **重写**成只含
     `{font_mul, font_lock_px, icon_visibility}` —— 而同一个文件里还住着 `image_mode`
     段（ask_on_exit / auto_on_start / interval_min / png_path / info_panel_w /
     pan_pad_scene）。用户动一次字体滑块或图标开关，看图模式的设置就被整段抹掉。
  ② `enter_view_mode()` 每次进都无条件 `_lock_saved = (stations_locked, labels_locked)`。
     在看图模式下定时出图/「立即生成」会二次进入 ⇒ 存下的是我们刚设的 (True, True)，
     退出后用户原本"只锁轨迹、不锁文字"的状态丢失，站名卡住拖不动。
  ③ `exit_view_mode()` 恢复锁态时直接给两个属性赋值，**没同步** `metro_render.STATIONS_LOCKED`
     ⇒ 界面显示已解锁、圆点照样拖不动。
  ④ `enter_view_mode()` 把 `_content_rect`（适配/居中基准）覆盖成位图范围，
     `exit_view_mode()` 从不还原 ⇒ 用过一次看图模式后整图适配与居中的基准就变了。
  ⑤ 看图模式下重新烘图时，上一张位图还在场景里 ⇒ 被一起烘进新图（残影）。
     本脚本用"纯品红色旧位图"当探针：新图里只要出现一个品红像素就算复现。

★ 离屏运行（不弹窗、不打扰用户）；写盘目标全部挪到临时目录，绝不碰真实数据。
运行：
    "C:/Users/29773/.workbuddy/binaries/python/envs/default/Scripts/python.exe" tools/_chk_view_mode_conflicts.py
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["METROEDITOR_NO_VIEW_START"] = "1"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF                     # noqa: E402
from PySide6.QtGui import QColor, QImage              # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

from ui import image_mode as IM                       # noqa: E402
from ui import metro_render as MR                     # noqa: E402
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
    def __init__(self, data_dir):
        self.DATA_DIR = str(data_dir)
        self.saved = 0

    def save(self):
        self.saved += 1


def magenta_count(img: QImage) -> int:
    """数一数图里有多少"纯品红"像素（数据里没有任何线路用 #FF00FF）。"""
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if c.red() > 200 and c.green() < 60 and c.blue() > 200:
                n += 1
    return n


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 800)
    app.processEvents()
    mv = win.map_view

    work = Path(tempfile.mkdtemp(prefix="chk_view_conflicts_"))
    try:
        stub = StubDM(ROOT / "data")          # 临时数据目录用真实数据当"只读源"
        win.dm = stub

        # ---------------------------------------------------------- ① 设置合并
        print("--- ① 字体/图标设置不许抹掉 image_mode 段 ---")
        sfile = work / "view_settings.json"
        sfile.write_text(json.dumps({
            "image_mode": {"ask_on_exit": False, "interval_min": 7, "info_panel_w": 400},
            "font_mul": 1.0,
        }, ensure_ascii=False), encoding="utf-8")
        mv.view_settings_file = lambda: str(sfile)          # 只改本实例，不动真实路径
        ok("构造时有 font_mul / font_lock_px 可写", hasattr(mv, "_font_mul") and hasattr(mv, "_font_lock_px"))
        mv._save_view_settings()
        d = json.loads(sfile.read_text(encoding="utf-8"))
        ok("image_mode 段还在", "image_mode" in d, sorted(d.keys()))
        ok("ask_on_exit 没被抹掉", (d.get("image_mode") or {}).get("ask_on_exit") is False,
           d.get("image_mode"))
        ok("interval_min 没被抹掉", (d.get("image_mode") or {}).get("interval_min") == 7)
        ok("自己的键也写进去了", d.get("font_mul") == mv._font_mul and "font_lock_px" in d,
           {k: d.get(k) for k in ("font_mul", "font_lock_px")})
        ok("image_mode 读回来仍是用户的设置（反向验证）",
           IM.load_settings(str(work)).get("interval_min") == 7)

        # ---------------------------------------------------------- ②③ 锁态
        print("--- ②③ 看图模式两次进入 / 退出后的锁态 ---")
        mv.set_drag_locks(True, False)          # 用户原始状态：锁轨迹、不锁文字
        box = QRectF(mv.scene_.sceneRect())
        img = QImage(16, 16, QImage.Format_ARGB32)
        img.fill(QColor(255, 0, 255))           # 品红探针（见 ⑤）

        mv.enter_view_mode(img, box)
        ok("进入看图后锁态被临时置为 (True, True)",
           (mv.stations_locked, mv.labels_locked) == (True, True))
        ok("备份的原始锁态 = (True, False)", mv._lock_saved == (True, False), mv._lock_saved)

        mv.enter_view_mode(img, box)            # 模拟"看图模式下又烘了一张再进来"
        ok("二次进入不会覆盖原始锁态（关键）", mv._lock_saved == (True, False), mv._lock_saved)

        mv.exit_view_mode()
        ok("退出后锁态回到用户原来的 (True, False)",
           (mv.stations_locked, mv.labels_locked) == (True, False),
           (mv.stations_locked, mv.labels_locked))
        ok("模块全局 STATIONS_LOCKED 与实例一致（以前会不一致）",
           bool(MR.STATIONS_LOCKED) is True, MR.STATIONS_LOCKED)

        mv.set_drag_locks(False, False)
        mv.enter_view_mode(img, box)
        mv.enter_view_mode(img, box)
        mv.exit_view_mode()
        ok("全解锁的用户态也能原样回来",
           (mv.stations_locked, mv.labels_locked) == (False, False)
           and bool(MR.STATIONS_LOCKED) is False,
           (mv.stations_locked, mv.labels_locked, MR.STATIONS_LOCKED))

        # ---------------------------------------------------------- ④ 适配基准
        print("--- ④ 适配/居中基准 _content_rect 用完要还原 ---")
        before = QRectF(mv._content_rect) if mv._content_rect is not None else None
        ok("构造后已有基准 _content_rect", before is not None)
        small = QRectF(0, 0, 50, 50)
        mv.enter_view_mode(img, small)
        ok("看图模式期间基准 = 位图范围", mv._content_rect == small, mv._content_rect)
        mv.exit_view_mode()
        ok("退出后基准还原成原来的", mv._content_rect == before, (mv._content_rect, before))

        # ---------------------------------------------------------- ⑤ 残影
        print("--- ⑤ 看图模式下重烘：旧位图不许被烘进新图 ---")
        wide = QRectF(mv.scene_.sceneRect())
        mv.enter_view_mode(img, wide)           # 场景里放一张"铺满"的品红位图
        ok("进看图后场景里确实有那张品红位图", mv._view_item is not None)
        out, r = IM.render_view_image(mv, 0.15)
        ok("烘图有结果", out is not None and not out.isNull(),
           None if out is None else (out.width(), out.height()))
        if out is not None and not out.isNull():
            n = magenta_count(out)
            ok("新图里一个品红像素都没有（旧位图没被烘进去）", n == 0, "品红像素=%d" % n)
        ok("旧位图烘完仍留在场景里（由 enter/exit 负责摘）", mv._view_item is not None)

        print("--- ⑤b 探针灵敏度：把旧位图显式打开再画，必须数得到品红 ---")
        from PySide6.QtGui import QPainter
        mv._restore_vector_items()          # 还原成"烘图那一刻"的可见性
        mv._view_item.setVisible(True)      # 手动显式打开 = 旧实现的样子
        base = mv._elements_rect(force=True).adjusted(-120, -120, 120, 120)
        pw, ph = max(2, int(base.width() * 0.15)), max(2, int(base.height() * 0.15))
        probe = QImage(pw, ph, QImage.Format_ARGB32)
        probe.fill(QColor(255, 255, 255))
        pt = QPainter(probe)
        try:
            mv.scene_.render(pt, QRectF(0, 0, pw, ph), base)
        finally:
            pt.end()
        n2 = magenta_count(probe)
        ok("把旧位图打开后能数到品红（证明上面那条 0 是真的，不是探针失灵）",
           n2 > 0, "品红像素=%d" % n2)

        mv.exit_view_mode()
    finally:
        try:
            win.deleteLater()
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)

    print("\n== _chk_view_mode_conflicts 结果：%d 通过 / %d 失败 ==" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
