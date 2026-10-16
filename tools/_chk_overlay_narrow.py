# -*- coding: utf-8 -*-
"""回归 v2.7.33：窗口一窄，两个浮层不许把地图盖满。

查的**逻辑冲突**是：

    `_layout_overlays()` 的注释写着"两个浮层同时开着时，若合计宽到快把地图盖满，
    等比收缩，至少给地图留 MAP_MIN_VISIBLE（320px）露出来"，
    但紧接着两行又用 `LEGEND_MIN_W(160)` / `INFO_PANEL_MIN_W(360)` 把宽度
    **抬了回去** —— 两个下限之和 520px。主窗口又**没有**最小宽度（可以随便拉小）
    ⇒ 只要窗口宽度 < 840，那 320px 的承诺就必然落空，地图被两侧浮层盖满：
      看不见图、也点不到图。

    修法（v2.7.33）：把承诺做在**窗口**这一层 —— 主窗口最小宽度 =
    图例下限 + 详情下限 + 地图要留的 320px。窗口拉不到那么窄，承诺就永远成立。

判据：
  A. 正常宽度（≥1280）：两个浮层宽度照旧（= 记忆宽度限幅后的值），
     地图露出来 ≥ 320 —— 一行都不许变
  B. 想拉窄：窗口自己被最小宽度兜住（地图区 ≥ 840），地图露出来仍 ≥ 320
  C. 变异自检：把最小宽度和 MAP_MIN_VISIBLE 一起清零 ⇒ A/B 必须炸
     （证明判据不是恒真）

运行：
    ...\\python.exe tools/_chk_overlay_narrow.py
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="ovnarrow_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                    # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402
import ui.main_window as MW                                   # noqa: E402

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 3) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def measure(win, target_w: int, h: int = 900):
    """把窗口往 target_w 拉（拉不动就说明被最小宽度兜住），摆一次浮层再量。"""
    win.resize(target_w, h)
    pump(6)
    win._layout_overlays()
    pump(3)
    area = win.map_area
    W = area.width()
    lw = win.legend_panel.width() if win.legend_panel.isVisible() else 0
    iw = win.info_wrap.width() if win.info_wrap.isVisible() else 0
    return W, lw, iw


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(10)
    if not win.legend_panel.isVisible():
        win._on_toggle_legend(True)
    if not win.info_wrap.isVisible():
        win._on_toggle_info_panel()
    pump(6)
    ok("前提：左右两个浮层都开着",
       win.legend_panel.isVisible() and win.info_wrap.isVisible())

    print("===== A 正常宽度：照旧（地图露 ≥ 320，浮层宽度正常） =====")
    seen = {}
    for wt in (1600, 1480, 1280):
        W, lw, iw = measure(win, wt)
        seen[wt] = (W, lw, iw)
        ok(f"A 窗口 {wt}（地图区 {W}）：地图露出 {W - lw - iw}px ≥ 320",
           W - lw - iw >= 320, f"图例 {lw} / 详情 {iw}")
    ok("A0 两个浮层真的都占了宽度（不是 0 宽度的空跑）",
       all(v[1] > 0 and v[2] > 0 for v in seen.values()))
    ok("A1 窗口 1600 时两浮层比 1280 时不更窄（没被压扁）",
       seen[1600][1] + seen[1600][2] >= seen[1280][1] + seen[1280][2],
       f"{seen[1600][1]}+{seen[1600][2]} vs {seen[1280][1]}+{seen[1280][2]}")

    print("===== B 想拉窄：最小宽度兜住，地图仍露 ≥ 320 =====")
    need_min = (win.legend_panel.minimumWidth()
                + win.info_panel.minimumWidth() + MW.MAP_MIN_VISIBLE)
    ok(f"B0 主窗口设了最小宽度 ≥ {need_min}",
       win.minimumWidth() >= need_min, f"实际 {win.minimumWidth()}")
    for wt in (1100, 900, 840, 600, 400):
        W, lw, iw = measure(win, wt)
        ok(f"B 想拉到 {wt}（实际窗口 {win.width()} / 地图区 {W}）"
           f"：地图露出 {W - lw - iw}px ≥ 320",
           W - lw - iw >= 320, f"图例 {lw} / 详情 {iw}")

    print("===== C 变异自检：把最小宽度和 MAP_MIN_VISIBLE 一起清零 ⇒ 必须炸 =====")
    _mw, _mmv = win.minimumWidth(), MW.MAP_MIN_VISIBLE
    try:
        win.setMinimumWidth(0)
        MW.MAP_MIN_VISIBLE = 0
        W, lw, iw = measure(win, 600)
        ok("C1 变异后窗口能拉到很窄、地图被盖满（证明 A/B 判据在岗）",
           (W - lw - iw) < 320,
           f"窗口 {win.width()} / 地图区 {W}，露出 {W - lw - iw}px")
    finally:
        win.setMinimumWidth(_mw)
        MW.MAP_MIN_VISIBLE = _mmv
    pump(4)
    measure(win, 1480)

    print()
    print(f"== _chk_overlay_narrow 结果：{PASS} 通过 / {FAIL} 失败 ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
