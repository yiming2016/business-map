# -*- coding: utf-8 -*-
"""探针：sprite 清扫的一次 tick 里，钱花在哪？

已知：松手后 1.2s 内 _sprite_sweep_tick 平均 5.46ms/次 × 71 次 = 持续顿挫。
要分清是
    (a) 扫描 379 个站点的"是否过期"(sprite_stale) 太贵，还是
    (b) 真正重建 sprite(render_sprite) 太贵，还是
    (c) 重建后触发的重绘太贵。
并统计：一次收尾后到底有多少个 sprite 过期（决定清扫要跑多久）。

运行：python tools/_probe_sweep_cost.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _wheel(vp, pos, delta):
    QApplication.sendEvent(vp, QWheelEvent(
        QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


def pump(ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.0005)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(400)

    mv = win.map_view
    vp = mv.viewport()
    items = list(mv.station_items.values())
    dpr = mv.devicePixelRatioF()
    print(f"视口 {vp.width()}x{vp.height()}  dpr={dpr:.2f}  scale={mv._scale:.4f}  "
          f"站点 {len(items)}")

    # --- 收尾后立刻统计"过期数"与单项成本 ---
    for pos in (QPoint(400, 400), QPoint(430, 400)):
        _wheel(vp, pos, 120)
        pump(30)
    pump(500)                       # 让收尾发生
    pump(200)
    mv._sprite_sweep.stop()         # 冻结清扫，单独量

    stale = [it for it in items if it.sprite_stale(dpr)]
    print(f"\n收尾后 sprite 过期数：{len(stale)} / {len(items)}")

    # (a) 扫描成本
    sample = items[:200]
    t0 = time.perf_counter()
    for it in sample:
        it.sprite_stale(dpr)
    t_scan = (time.perf_counter() - t0) / len(sample)
    print(f"(a) sprite_stale 单项  {t_scan*1e6:7.1f}µs   "
          f"→ 全量 379 个 = {t_scan*379*1000:.2f}ms")

    # (b) 重建成本（只重建过期的那批）
    if stale:
        t0 = time.perf_counter()
        for it in stale:
            it.render_sprite(dpr)
        t_render = (time.perf_counter() - t0) / len(stale)
        print(f"(b) render_sprite 单项 {t_render*1e6:7.1f}µs   "
              f"→ 重建 {len(stale)} 个 = {t_render*len(stale)*1000:.1f}ms")

    # (c) 重建后同步重绘一次要多久（这才是"重建 → 屏幕更新"的真实代价）
    for it in items[:12]:
        it.render_sprite(dpr)
    t0 = time.perf_counter()
    mv.viewport().repaint()
    print(f"(c) 12 个 sprite 重建后整屏 repaint = "
          f"{1000*(time.perf_counter()-t0):.1f}ms")

    # 统计 8 个/次预算下，清扫要跑多少次
    mv._start_sprite_sweep()
    t0 = time.perf_counter()
    n_ticks = 0
    while mv._sprite_sweep.isActive() and time.perf_counter() - t0 < 3.0:
        QApplication.processEvents()
        n_ticks += 1
        time.sleep(0.002)
    print(f"\n清扫从启动到结束：{1000*(time.perf_counter()-t0):.0f}ms  "
          f"（已跑 {n_ticks} 轮 processEvents，"
          f"定时器{'仍在跑' if mv._sprite_sweep.isActive() else '已停'}）")

    # ★ 关键：清扫跑完（或超时）后还剩多少"永远作废"的 sprite？
    #   若 _sprite_sig_key() 返回 None，render_sprite() 只会把 _sprite 置空，
    #   sprite_stale() 永远为 True → 清扫死循环、永远啃主线程。
    left = [it for it in items if it.sprite_stale(dpr)]
    print(f"\n清扫后仍过期：{len(left)} / {len(items)} 个")
    for it in left[:10]:
        br = it.boundingRect()
        w = br.width() * it._view_scale
        h = br.height() * it._view_scale
        print(f"   {it.station_id:12s} '{it.data.get('station_name','')[:10]}'  "
              f"br={br.width():.1f}x{br.height():.1f}  "
              f"屏幕 {w:.1f}x{h:.1f}  sig_is_None={it._sprite_sig_key(dpr) is None}  "
              f"_sprite_is_None={it._sprite is None}")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
