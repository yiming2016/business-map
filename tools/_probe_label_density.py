# -*- coding: utf-8 -*-
"""探针：站名"能挤就挤"最多能挤出多少？把几个开关扫一遍（走真实排版代码）。

背景：缩到最小时 379 个站只有 35 个站名显示得出来（9%），地图中心一片圆点没名字。
本探针回答"到底能挤出多少、代价是什么"，据此再定参数。

用法：
    python tools/_probe_label_density.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont                           # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

import ui.metro_render as MR                              # noqa: E402
import ui.map_view as MV                                  # noqa: E402
from ui.main_window import MainWindow                     # noqa: E402


def pump(n=14):
    for _ in range(n):
        QApplication.processEvents()


def layout(win, scale, font_min, pad_tight, tol, avoid_dots):
    """按给定开关跑一遍真实排版，返回 (可见站名数, 排版耗时ms, 平均重叠率)。"""
    mv = win.map_view
    # 缩放到目标
    ratio = scale / max(mv._scale, 1e-9)
    mv._apply_zoom_transform(ratio, mv.viewport().rect().center())
    mv._sync_zoom_state()

    MR.SCREEN_FONT_MIN_PX = font_min
    MV.LABEL_PAD_TIGHT = pad_tight
    MV.LABEL_PAD = pad_tight          # 贴着下限量，干脆都收紧
    MV.LABEL_OVERLAP_TOL = tol
    MV.LABEL_AVOID_DOTS = avoid_dots

    mv._apply_station_scale_all()     # 让字号真的按 font_min 生效
    pump()
    mv._invalidate_nn()
    t0 = time.perf_counter()
    mv._update_label_visibility()
    ms = (time.perf_counter() - t0) * 1000.0
    pump()

    shown = [it for it in mv.station_items.values() if it._label_on]
    n = len(shown)
    # 实测重叠：两两求交，算"重叠面积占自身面积"的平均最大值
    # （只对可见的、且相邻的站名算 —— 全量 O(N²)=379² 也就 7 万次，够快）
    rects = [(it.station_id, it.label_scene_rect(it.label_side())) for it in shown]
    worst = {}
    for i in range(len(rects)):
        sid_i, ri = rects[i]
        if ri.width() <= 0.1:
            continue
        ai = max(ri.width() * ri.height(), 1e-9)
        for j in range(i + 1, len(rects)):
            sid_j, rj = rects[j]
            if rj.width() <= 0.1:
                continue
            inter = ri.intersected(rj)
            if inter.isEmpty():
                continue
            a = inter.width() * inter.height()
            aj = max(rj.width() * rj.height(), 1e-9)
            worst[sid_i] = max(worst.get(sid_i, 0.0), a / ai)
            worst[sid_j] = max(worst.get(sid_j, 0.0), a / aj)
    ov = (sum(worst.values()) / len(worst)) if worst else 0.0
    bad = sum(1 for v in worst.values() if v > 0.5)
    return n, ms, ov, bad


COMBOS = [
    ("① 现状（10px / 留白3 / 不许压）", 10.0, 3.0, 0.0, True),
    ("② 只把留白收紧 3→1px",          10.0, 1.0, 0.0, True),
    ("③ 字号下限 10→9px",             9.0, 1.0, 0.0, True),
    ("④ 字号下限 10→8px",             8.0, 1.0, 0.0, True),
    ("⑤ 放宽重叠：允许压 25%",         10.0, 1.0, 0.25, True),
    ("⑥ 放宽重叠：允许压 50%",         10.0, 1.0, 0.50, True),
    ("⑦ 允许压在别站圆点上",           10.0, 1.0, 0.0, False),
    ("⑧ ③+⑤：9px + 压25%",           9.0, 1.0, 0.25, True),
    ("⑨ ④+⑦：8px + 压圆点",           8.0, 1.0, 0.0, False),
    ("⑩ ④+⑥+⑦：8px+压50%+压圆点",     8.0, 1.0, 0.50, False),
]


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)

    mv = win.map_view
    total = len(mv.station_items)
    floor = mv._min_scale_for_viewport()
    print(f"站点总数 {total}  缩放下限 {floor:.4f}  视口 "
          f"{mv.viewport().width()}x{mv.viewport().height()}")

    original = (MR.SCREEN_FONT_MIN_PX, MV.LABEL_PAD, MV.LABEL_PAD_TIGHT,
                MV.LABEL_OVERLAP_TOL, MV.LABEL_AVOID_DOTS)
    try:
        for scale, tag in ((floor, "缩到最小"), (0.16, "中等"), (0.30, "接近全出")):
            print(f"\n===== scale={scale:.4f}（{tag}）=====")
            print(f"{'方案':<32}{'站名数':>8}{'占比':>8}{'排版':>9}{'平均重叠':>10}{'>50%叠':>9}")
            for name, fmin, pad, tol, dots in COMBOS:
                n, ms, ov, bad = layout(win, scale, fmin, pad, tol, dots)
                print(f"{name:<32}{n:>8}{n * 100.0 / total:>7.1f}%{ms:>8.1f}ms"
                      f"{ov * 100:>9.1f}%{bad:>9}")
    finally:
        (MR.SCREEN_FONT_MIN_PX, MV.LABEL_PAD, MV.LABEL_PAD_TIGHT,
         MV.LABEL_OVERLAP_TOL, MV.LABEL_AVOID_DOTS) = original

    win.close()
    pump()
    return 0


if __name__ == "__main__":
    sys.exit(main())
