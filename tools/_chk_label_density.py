# -*- coding: utf-8 -*-
"""回归检查：站名"缩小也能尽量显示全"（v2.5.2）

用户需求原话：
    「在缩小的情况下，尽可能的显示出所有站点(如遇堆叠则选择性显示)」

改动前的实测：缩到最小时 379 个站只有 35~102 个站名显示得出来，
地图中心一大片圆点一个名字都没有（看全局时等于"站点全没了"）。

本脚本要守住四件事：
  A 八向摆放 —— 站名能在圆点的右/左/上/下 + 4 个斜角共 8 个位置里找空位
  B 两轮排版 —— 第一轮严格（留白 3px、零重叠，与改动前一致），第二轮才收紧留白
                并允许轻微重叠（只动第一轮没放下的那批，不会挤走已放好的）
  C 覆盖率   —— 缩到最小时显示站名数不能低于底线（防退化），且随缩放单调不减
  D 不许糊团 —— 没有任何两个站名"互相压掉超过一半"（这就是"遇堆叠则选择性显示"的下限）

运行：
    C:\\Users\\29773\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe tools/_chk_label_density.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF                        # noqa: E402
from PySide6.QtGui import QFont                           # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402

import ui.map_view as MV                                  # noqa: E402
from ui.main_window import MainWindow                     # noqa: E402
from ui.metro_render import LABEL_SIDES, LABEL_SIDES_CARDINAL  # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def set_scale(mv, scale) -> None:
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def overlap_stats(mv) -> tuple:
    """返回 (可见数, 最严重的单站名重叠率, 重叠>50% 的个数)。"""
    shown = [it for it in mv.station_items.values() if it._label_on]
    rects = [(it.station_id, it.label_scene_rect(it.label_side())) for it in shown]
    worst: dict = {}
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
    mx = max(worst.values()) if worst else 0.0
    bad = sum(1 for v in worst.values() if v > 0.5)
    return len(shown), mx, bad


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)          # ★ 真机尺寸：地图像素 874x829
    win.show()
    pump(40)
    mv = win.map_view
    box = mv.station_items
    total = len(box)
    floor = mv._min_scale_for_viewport()

    print("\n===== A 八向摆放（几何）=====")
    check("站名候选方向 = 4 正方向 + 4 斜角",
          set(LABEL_SIDES) == set(LABEL_SIDES_CARDINAL)
          | {"rt", "lt", "rb", "lb"},
          f"{LABEL_SIDES}")
    it = next(iter(box.values()))
    it.apply_view_scale(0.5)
    # ★ v2.6.24：原来拿 `radius()`（= 包围盒**最大**那一边）去跟上下方向比，
    #   对**横着放**的药丸根本不成立 —— 它竖向只有 10px、横向 38px，
    #   "摆在上面"的站名明明是对的，却因为比不过那个 38px 被判失败。
    #   改成**按轴分别比**：上下跟竖向半高比、左右跟横向半宽比。
    _k = 1.0 / 0.5                  # 场景单位 = 屏幕像素 ÷ 视图缩放
    _hs = it.screen_half()          # (半宽, 半高)，屏幕像素
    r_x, r_y = _hs[0] * _k, _hs[1] * _k
    r_dot = max(r_x, r_y)
    for side, ok in (("right", lambda b: b.left() > r_x * 0.9 and abs(b.center().y()) < 2),
                     ("left", lambda b: b.right() < -r_x * 0.9),
                     ("top", lambda b: b.bottom() < -r_y * 0.9),
                     ("bottom", lambda b: b.top() > r_y * 0.9),
                     ("rt", lambda b: b.left() > 0 and b.bottom() < 0),
                     ("lt", lambda b: b.right() < 0 and b.bottom() < 0),
                     ("rb", lambda b: b.left() > 0 and b.top() > 0),
                     ("lb", lambda b: b.right() < 0 and b.top() > 0)):
        b = it._label_box(side)
        check(f"  「{side}」方向摆在圆点的正确一侧", ok(b),
              f"box=({b.left():.0f},{b.top():.0f},{b.width():.0f}x{b.height():.0f}) "
              f"半径={r_dot:.1f}")

    print("\n===== B 两轮排版：第一轮严格，第二轮才放宽 =====")
    check("第一轮留白 = LABEL_PAD（3px，与改动前一致）", MV.LABEL_PAD >= 2.0,
          f"{MV.LABEL_PAD}")
    check("第二轮留白 = LABEL_PAD_TIGHT（更紧才有机会塞进去）",
          MV.LABEL_PAD_TIGHT < MV.LABEL_PAD, f"{MV.LABEL_PAD_TIGHT}")
    check("第二轮允许的重叠上限不为 0 也不激进（0 < tol <= 0.25）",
          0.0 < MV.LABEL_OVERLAP_TOL <= 0.25, f"{MV.LABEL_OVERLAP_TOL}")
    set_scale(mv, 1.0)
    n1, mx1, bad1 = overlap_stats(mv)
    check("缩放 1.0 时基本全显示（第一轮就放得下）", n1 >= total - 5, f"{n1}/{total}")
    check("缩放 1.0 时没有糊团", bad1 == 0, f"最严重 {mx1 * 100:.1f}%")

    print("\n===== C 覆盖率：缩小后要尽量显示全 =====")
    counts = []
    for s in (floor, 0.16, 0.30, 1.0):
        set_scale(mv, s)
        n, mx, bad = overlap_stats(mv)
        counts.append((s, n))
        print(f"      缩放 {s:.4f}：站名 {n:>3}/{total}（{n * 100.0 / total:>5.1f}%）"
              f" 最严重重叠 {mx * 100:>4.1f}%")

    n_min = counts[0][1]
    check("★ 缩到最小时站名数 >= 180（改前只有 35~102，防退化）", n_min >= 180,
          f"{n_min}/{total} = {n_min * 100.0 / total:.1f}%")
    check("  缩放 0.16 时站名数 >= 320（改前 233）",
          dict(counts)[0.16] >= 320, f"{dict(counts)[0.16]}")
    check("  缩到最小时覆盖率 >= 50%", n_min >= total * 0.5,
          f"{n_min * 100.0 / total:.1f}%")
    # ★ 放大过程中站名只会变多、不该变少（两轮排版没有"跨阈值跳变"）
    # ★★ v2.6.27：允许跨过 LABEL_RING_MIN_SCALE(0.20) 时**掉 ≤4 个**。
    #   原因：0.20 起站名多了一批"往外让一圈"的候选位，少数站名因此挪到
    #   更远处、暂时跟邻站名判成冲突而隐藏 —— 这是**用户点名要的改动**
    #   （原话「缩小到一定尺寸文字完全偏离正确位置」）的必然代价：
    #   小档不让位 ⇒ 字骑在隔壁站头上；让位 ⇒ 个别站名先藏一下。
    #   两害相权取"不错位"。掉档超过 4 个说明让位过头了，仍要抓。
    # ★★ v2.6.27：只比**缩得到的**档位。最小缩放现在是 MIN_VIEW_SCALE(0.18)，
    #   脚本里那个 0.12 档用户已经缩不到了 —— 拿一个不可达的档来判"掉档"
    #   是假失败（实测正是它：0.18:364 → 0.12:295）。
    import ui.map_view as _MV
    counts = [(s, n) for s, n in counts if s >= _MV.MIN_VIEW_SCALE - 1e-6]
    drops = [(counts[i][0], counts[i][1], counts[i + 1][0], counts[i + 1][1])
             for i in range(len(counts) - 1) if counts[i + 1][1] < counts[i][1]]
    worst_drop = max((c[1] - c[3] for c in drops), default=0)
    check("  放大过程中站名数不掉档（允许跨外圈阈值时掉 ≤4 个）",
          worst_drop <= 4,
          " → ".join(f"{s:.3f}:{n}" for s, n in counts)
          + (f"   掉档：{drops}" if drops else ""))

    print("\n===== D 不许糊团：没有任何站名被压掉超过一半 =====")
    for s in (floor, 0.16, 0.30, 1.0):
        set_scale(mv, s)
        n, mx, bad = overlap_stats(mv)
        check(f"  缩放 {s:.3f}：没有「互相压掉 >50%」的站名", bad == 0,
              f"最严重 {mx * 100:.1f}%，>50% 的有 {bad} 个")

    print("\n===== E 排版耗时（缩放收尾时跑一次）=====")
    # ★ 量法：_update_label_visibility() 每次都是全量重算（没有内部记忆），
    #   所以"同一次缩放里连测 3 遍"是等价工作量，取**中位**即可抹掉偶发的
    #   调度抖动。以前只取"第一发的最大值"（4 个缩放点各 1 次），
    #   实测同一份代码在不同进程里能跑出 55~66ms / 145~165ms 的散布，
    #   阈值贴着这个散布 → 必然flake（v2.5.4 实测两次擦线）。
    REPEAT = 3
    worst_cached = worst_nn = 0.0
    for s in (floor, 0.16, 0.30, 1.0):
        set_scale(mv, s)
        c, w = [], []
        for _ in range(REPEAT):
            t0 = time.perf_counter()      # nn 已缓存（平移/缩放时的常态）
            mv._update_label_visibility()
            c.append((time.perf_counter() - t0) * 1000.0)
            mv._invalidate_nn()           # 站点被拖动后才需要重算最近邻
            t0 = time.perf_counter()
            mv._update_label_visibility()
            w.append((time.perf_counter() - t0) * 1000.0)
        worst_cached = max(worst_cached, statistics.median(c))
        worst_nn = max(worst_nn, statistics.median(w))
    print(f"      最近邻已缓存 {worst_cached:.1f}ms   需重算最近邻 {worst_nn:.1f}ms")
    # 标定（874x829 视口 / 379 站点 / 每点取 3 次中位，v2.5.4 新旧字号策略
    # 各跑 3 遍实测）：
    #   常态 55~66ms —— 热点固定在"缩到最小"那一档（要放 232 个站名、
    #   碰撞最多）。旧代码同样是 56~63ms，所以这 50+ms 是"低缩放下站名本来
    #   就多"的固有成本，不是回归。
    #   最坏 145~165ms —— 含 O(N²) 最近邻重算，只在拖动站点后才发生。
    # ★★ 阈值 90 / 200 是**贴着散布**定的，机器一忙就 flake（v2.6.12 一次
    #    批量跑回归实测 107.0 / 215.4ms，单独跑又是 24/24 全过）
    #    —— 跟 MEMORY §5.1 一个毛病：阈值压在噪声地板上 ⇒ 抛硬币。
    #    改成：**绝对阈值只用来抓"彻底炸了"**（200 / 400，留 ~2 倍余量），
    #    真正的"算法有没有退化"交给下面那条**变异自检**：同一进程里先量正常、
    #    再量一个故意做成 O(N²) 的版本，慢不到 3 倍就说明这条判据是瞎的。
    check("常态（最近邻已缓存）单次排版 < 200ms（只抓彻底炸了）",
          worst_cached < 200.0, f"最慢 {worst_cached:.1f}ms")
    check("最坏（含 O(N²) 最近邻重算）单次排版 < 400ms（只抓彻底炸了）",
          worst_nn < 400.0, f"最慢 {worst_nn:.1f}ms")

    # E3 变异：把碰撞网格的格子撑到无限大 ⇒ 所有障碍落进同一格，
    #    每次 `collides()` 都要扫全部 ~400 个障碍（真正的 O(N²) 退化）。
    #    ★ 用模块常量 `LABEL_CELL_MIN` 打（`_update_label_visibility` 里
    #      每次调用都重新读它），不改被测代码。
    old_cell_min = MV.LABEL_CELL_MIN
    MV.LABEL_CELL_MIN = 1e9
    set_scale(mv, floor)
    t0 = time.perf_counter()
    mv._update_label_visibility()
    bad_ms = (time.perf_counter() - t0) * 1000.0
    MV.LABEL_CELL_MIN = old_cell_min
    check("变异（碰撞网格退化成 O(N²)）后耗时**明显变慢** ⇒ E 判据真在上岗",
          bad_ms > worst_cached * 3.0,
          f"变异后 {bad_ms:.0f}ms vs 正常 {worst_cached:.1f}ms"
          f"（{bad_ms / max(worst_cached, 1e-6):.1f}×）")

    win.close()
    pump()
    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    if FAILED:
        print("失败项：")
        for n in FAILED:
            print("  -", n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
