# -*- coding: utf-8 -*-
"""检查：**分条揭开**的两幅画面对不对得上（快照合成帧 vs 真实场景渲染）。

要守的命门（都在 v2.5.3 动过，必须有人看着）：
  ① 快照 label 的对齐必须是「左上」。若是 QLabel 默认的［左+垂直居中］，
     把 label 高度从底部削掉时 pixmap 会跟着垂直重新居中，
     露出来的是**快照中间一段** → 整个揭开过程画面错位。
  ② `_zoom_step` 收敛时补的那一帧 + `_begin_reveal` 的"帧没脏就不重合成"
     —— 判断错了，揭开的条带就会与真实渲染差一点点（历史悠久的"错位"）。

判据：揭开开始时把快照合成帧原样抄下来，揭开结束后截真实渲染的视口，
      两幅图**必须几乎一样**（它们本就该是同一幅画面：一个用 sprite 贴图，
      一个走矢量绘制，只允许抗锯齿级别的差异）。

运行：python tools/_chk_reveal_align.py
     两张对比图会存到 logs/_reveal_cmp_*.png（可直接打开看）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

LOGS = ROOT / "logs"
PASS = FAIL = 0
CAPTURED: dict = {}


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}   {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


def pump(ms: float) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.002)


def wheel(vp, pos, delta):
    QApplication.sendEvent(vp, QWheelEvent(
        QPointF(pos), vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


def diff_ratio(img_a, img_b):
    """降采样后比较两幅图。

    ★ 为什么必须降采样：合成帧用 drawPixmap 贴 sprite、真实渲染走矢量绘制，
      两者对"半像素"的抗锯齿取整不同 → 每一处文字/线条边缘都会差一点
      （实测 4~5% 的像素，但全是"空心轮廓"、字芯完全一致，肉眼不可见）。
      直接逐像素比会把这种无害噪声判成失败。
      降到 1/4（4×4 块取均值）后，亚像素噪声被抹平；而真正的错位
      （例如 pixmap 垂直居中导致整幅画错开几百像素）依然是巨大的差异。
    """
    if img_a.size() != img_b.size():
        return 1.0, 0.0, f"尺寸不同 {img_a.width()}x{img_a.height()} vs " \
                         f"{img_b.width()}x{img_b.height()}"
    a = img_a.convertToFormat(QImage.Format.Format_RGB32)
    b = img_b.convertToFormat(QImage.Format.Format_RGB32)
    w, h = a.width(), a.height()
    ba, bb = a.constBits().tobytes(), b.constBits().tobytes()
    B = 4
    bw, bh = w // B, h // B
    total = 0
    bad = 0
    sad = 0
    for by in range(bh):
        y0 = by * B
        for bx in range(bw):
            x0 = bx * B
            sa = sb = 0
            for dy in range(B):
                row = (y0 + dy) * w
                for dx in range(B):
                    i = (row + x0 + dx) * 4
                    sa += ba[i] + ba[i + 1] + ba[i + 2]
                    sb += bb[i] + bb[i + 1] + bb[i + 2]
            d = abs(sa - sb) / (B * B * 3)      # 该块的通道均值差
            total += 1
            sad += d
            if d > 16:
                bad += 1
    return (bad / max(total, 1)), (sad / max(total, 1)), \
           f"{bad}/{total} 块差异>16，平均块差 {sad/max(total,1):.2f}"


def worst_band(img_a, img_b, nbands: int) -> float:
    """把图按横带切成 nbands 段，返回差异最严重那一段的"块差异>16"占比。

    ★ 为什么要按横带看：错位 bug（例如 pixmap 垂直居中）的特征是
      **某一条横带整体错**，而整幅平均会被其它正确的带子稀释掉、
      看起来"只是有点噪声"。分带统计能让它无处躲。
    """
    a = img_a.convertToFormat(QImage.Format.Format_RGB32)
    b = img_b.convertToFormat(QImage.Format.Format_RGB32)
    w, h = a.width(), a.height()
    if b.size() != a.size():
        return 1.0
    ba, bb = a.constBits().tobytes(), b.constBits().tobytes()
    B = 4
    bh = h // B
    per = max(1, bh // nbands)
    stats = [[0, 0] for _ in range(nbands)]
    for by in range(bh):
        band = min(nbands - 1, by // per)
        y0 = by * B
        for bx in range(w // B):
            x0 = bx * B
            sa = sb = 0
            for dy in range(B):
                row = (y0 + dy) * w
                for dx in range(B):
                    i = (row + x0 + dx) * 4
                    sa += ba[i] + ba[i + 1] + ba[i + 2]
                    sb += bb[i] + bb[i + 1] + bb[i + 2]
            stats[band][1] += 1
            if abs(sa - sb) / (B * B * 3) > 16:
                stats[band][0] += 1
    return max((bad / max(tot, 1)) for bad, tot in stats)


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    win.activateWindow()
    pump(500)

    mv = win.map_view
    vp = mv.viewport()
    print(f"视口 {vp.width()}x{vp.height()}  scale={mv._scale:.4f}  站点 {len(mv.station_items)}")
    print()

    print("A 快照 label 的对齐（必须左上，否则揭开时画面错位）")
    al = mv._snap_label.alignment()
    ok("对齐含 AlignTop", bool(al & Qt.AlignTop), f"alignment={al}")
    ok("对齐含 AlignLeft", bool(al & Qt.AlignLeft), "")

    # ★ 变异测试：故意把对齐改回 QLabel 的默认（左+垂直居中），
    #   用来验证本检查**确实抓得住**这个 bug —— 抓不住的回归等于没有回归。
    if "--mutate-align" in sys.argv:
        mv._snap_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        print("  ！已注入变异：对齐改成［左+垂直居中］（B 段应当全部失败）")

    # ★ 钩住"揭开中途"这一刻。为什么必须抓中途：
    #   对齐只在 label **被削矮之后**才起作用 —— 满屏时 pixmap 1:1 贴满，
    #   居中与左上毫无区别（实测变异测试：满屏帧的数字一模一样，抓不住 bug）。
    #   vp.grab() 会直接渲染整棵控件树（含 label 子控件），所以能拿到
    #   "快照条 + 真实场景条"拼接的真实中间态。
    orig_begin = mv._begin_reveal
    st = {"mid": None, "frame": None}

    def hooked_begin():
        orig_begin()
        st["frame"] = mv._snap_label.pixmap().toImage().copy()
        st["scale"] = mv._scale
        mv._sprite_sweep.stop()       # 对比期间别让画面自己变

    def observer():
        # ★ 必须挂"额外的槽"而不是替换 mv._reveal_tick：
        #   定时器连的是**构造时**绑定的原始方法，替换属性对它无效。
        # ★★ 也别再用 st.clear() 复用字典：清空后观察者访问 st["mid"] 会
        #   KeyError，而 Qt 会把槽里的异常悄悄吞掉 —— 检查会"假装通过/失败"。
        if st.get("mid") is None and 0.35 <= mv._reveal_y / max(vp.height(), 1) <= 0.75:
            st["mid"] = vp.grab().toImage()      # 立刻同步渲染整棵控件树
            st["mid_rest"] = mv._snap_label.height()

    mv._begin_reveal = hooked_begin
    mv._reveal.timeout.connect(observer)

    print("\nB 揭开进行到一半时截屏  vs  揭开结束后的真实渲染（像素一致性）")
    print("  —— 上半幅是快照（贴图）、下半幅已是真实场景；两者本就该是同一幅画")
    scales = []
    # ★ v2.6.31：原来只滚到 scale≈0.24 —— 那一档圆点尺寸几乎不随缩放变，
    #   正好是"圆点冻结 + 收尾跳变"这个 bug 的**盲区**（改前也照样通过）。
    #   补几格把缩放推到 1.0 上下，圆点半径差 2 倍以上，才抓得住。
    # ★★ 还要**大跨度**：1.33×/次的手势里圆点半径只差 1.2px，块差异淹没在
    #   抗锯齿里（实测变异"用冻结缩放画圆点"照样通过 —— 判据等于没有）。
    #   补两次 0.18↔1.0（≈5.6×）的大跨：那时圆点半径 3.4 vs 11.76，差 8px，
    #   冻结 bug 立刻现形。
    for i, delta in enumerate([-120, -120, 120, 120, 240,
                               -1440, 1440, -1440, 1440]):
        st["mid"] = None
        st["frame"] = None
        wheel(vp, QPoint(vp.width() // 2, vp.height() // 2), delta)
        t0 = time.perf_counter()
        while st.get("mid") is None and time.perf_counter() - t0 < 1.5:
            QApplication.processEvents()
            time.sleep(0.002)
        if st.get("mid") is None:
            ok(f"第{i + 1}次：抓到了揭示中途", False,
               f"没抓到中途帧（揭开很快，或钩子异常被 Qt 吞掉）"
               f" scale={st.get('scale')}")
            continue
        # 等揭开彻底结束 + 真实渲染落定
        t0 = time.perf_counter()
        while (mv._zoom_snap is not None or mv._reveal.isActive()) \
                and time.perf_counter() - t0 < 2.0:
            QApplication.processEvents()
            time.sleep(0.002)
        pump(60)
        mv._sprite_sweep.stop()
        real = vp.grab().toImage()
        mid = st["mid"]
        frame = st["frame"]
        r, mean_abs, detail = diff_ratio(mid, real)
        band = worst_band(mid, real, 8)
        p1 = LOGS / f"_reveal_cmp_{i + 1}_mid.png"
        p2 = LOGS / f"_reveal_cmp_{i + 1}_real.png"
        p3 = LOGS / f"_reveal_cmp_{i + 1}_frame.png"
        mid.save(str(p1))
        real.save(str(p2))
        frame.save(str(p3))
        scales.append(round(st["scale"], 4))
        print(f"  （中途：快照还剩 {st.get('mid_rest')}px 高）")
        print(f"    整幅：块差异>16 占 {r*100:.2f}%、平均块差 {mean_abs:.2f}"
              f"；最差横带 {band*100:.2f}%")
        # ★ v2.6.31：分档阈值。合成帧的圆点是**矢量实时画**，真实帧走
        #   DeviceCoordinateCache（**位图**）⇒ 小档圆点只有 3.4px，边缘抗锯齿
        #   差异占整幅比例很高（7~9%），那是管线差异不是错位；大档（scale≥0.5）
        #   圆点 11px 以上、且"尺寸跳变"只在大档才看得见，所以那里收紧到 5%。
        _big = st['scale'] >= 0.5
        _lim = (0.05, 3.0, 0.12) if _big else (0.12, 9.0, 0.30)
        ok(f"第{i + 1}次（scale {st['scale']:.3f}）：中途画面 == 最终画面",
           r < _lim[0] and mean_abs < _lim[1] and band < _lim[2],
           f"整幅 {r*100:.2f}%（最差横带 {band*100:.2f}%，平均块差 {mean_abs:.2f}）"
           f"→ {p1.name}/{p2.name}")

    print(f"\n刻度轨迹 {scales}")
    print(f"\n{'=' * 62}\n通过 {PASS} 项，失败 {FAIL} 项")
    print("全部通过 ✅" if FAIL == 0 else "★ 有失败项")
    win.close()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
