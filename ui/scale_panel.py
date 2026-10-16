# -*- coding: utf-8 -*-
"""v2.6.41：地图右上角的「整体缩放 / 字体缩放」双滑块（各带一把锁）。

放在这里而不是 map_view.py 里，是为了让面板**只管界面**：
它不认识 MapView，只往外发四个信号；反过来由 MapView 调 `set_zoom()` /
`set_font_mul()` 把当前状态同步回滑块（同步时 blockSignals，避免回环）。

两把锁的语义：
  🔒 整体缩放 —— 锁住当前缩放比例，**滚轮不再改变它**（防误触）。
     滑块本身仍可拖动（否则锁上就再也调不动了）。
  🔒 字体缩放 —— 锁住**字号的屏幕大小**，之后再怎么缩放地图，字都不跟着变
     （也就是 v2.6.38 之前的"字不随图放大"行为）。
     解锁 ⇒ 字号跟地图等比（默认）。
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QSlider,
                               QLabel, QToolButton, QSizePolicy, QWidget)

LOCK_ON = "🔒"
LOCK_OFF = "🔓"

# ★ v2.6.43（用户：「要紧贴右上角边缘，且融入进去，不要看起来作为一个凸出来的
#   模块」）：整块**不画底、不画框、不画圆角** —— 背景透明，只有控件本身有像素，
#   看起来就是"贴在地图上的两个滑块"，而不是一张卡片。
#   ★ 可读性靠**局部**手段：数字标签给一层 72% 白底（压在深色线路上也看得清），
#     锁按钮平时只有 emoji、hover/锁上才显形；滑块手柄蓝色（与浅底色差 >>80）。
_QSS = """
ScalePanel {
    background: transparent;
    border: none;
    border-radius: 0;
}
ScalePanel QLabel {
    background: rgba(255, 255, 255, 0.72);
    border: none;
    border-radius: 3px;
    padding: 0px 3px;
    color: #33404F;
    font: 11px "Microsoft YaHei";
}
ScalePanel QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    font: 13px "Segoe UI Emoji", "Microsoft YaHei";
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
}
ScalePanel QToolButton:hover {
    background: rgba(255, 255, 255, 0.85);
}
ScalePanel QToolButton:checked {
    background: rgba(232, 106, 106, 0.20);
}
ScalePanel QSlider::groove:horizontal {
    background: rgba(120, 132, 150, 0.45);
    height: 3px;
    border-radius: 2px;
}
ScalePanel QSlider::handle:horizontal {
    background: #2F6FED;
    width: 11px;
    margin: -4px 0;
    border-radius: 6px;
}
ScalePanel QSlider::sub-page:horizontal {
    background: #2F6FED;
    height: 3px;
    border-radius: 2px;
}
"""


class _WheelSlider(QSlider):
    """★ v2.6.52：面板上的滑块要"像控件"，不是"像装饰"。

    用户要求：① 鼠标悬浮在滑块上 ⇒ 换光标（左右箭头 = 可拖）；
              ② 鼠标在滑块上**滚轮** ⇒ 调这条滑块自己（整体缩放 / 字体缩放），
                 点一下再滚也一样，不用先把鼠标挪到地图上。

    ★★ 必须 `e.accept()`：滑块的 wheel 事件一旦被忽略，就会冒泡到下面的
       QGraphicsView ⇒ **一次滚动同时改了滑块和地图**（两件事一起动）。
    ★ 用 120 的累加器而不是"一格 = 一个 event"：触控板/高分辨率滚轮
       一格只给 1~3 的 angleDelta，直接按事件数走会一步窜到底。
    """

    WHEEL_UNIT = 120

    def __init__(self, parent=None, wheel_tick: int = 32):
        super().__init__(Qt.Horizontal, parent)
        self._wheel_tick = max(1, int(wheel_tick))
        self._acc = 0
        self.setCursor(Qt.SizeHorCursor)        # 左右箭头：一眼看出"能左右拖"
        self.setToolTip("拖动滑块，或在滑块上用滚轮调节")

    def wheelEvent(self, e):                    # noqa: N802
        d = e.angleDelta().y()
        if not d:
            e.ignore()                          # 横向滚/纯横滚：让给别人
            return
        self._acc += d
        moved = 0
        while abs(self._acc) >= self.WHEEL_UNIT:
            sign = 1 if self._acc > 0 else -1
            moved += sign * self._wheel_tick
            self._acc -= sign * self.WHEEL_UNIT
        if moved:
            self.setValue(self.value() + moved)
        e.accept()                              # ★ 不许冒泡到地图


class _TickBar(QWidget):
    """★ v2.6.53：缩放滑块正下方的**档位分隔线** —— 一眼看出"一共几档、现在在第几档"。

    档位取"显示倍率"的 2 的幂（1× / 2× / 4× / 8× / 16× / 32× / 64×）：
    ★ 滑块是**对数**刻度（`_zoom_of` 用 exp）⇒ 2 的幂在上面天然**等距**
      （间隔 = ln2 / ln(最大÷最小) ≈ 16.3%），数一下分隔线就知道有几档。
    ★ handle 宽 11px ⇒ 手柄中心只在 [5.5, w-5.5] 之间跑，刻度要按这个范围映射，
      否则两端的线会和手柄对不上。
    """

    H = 5                 # 刻度条高度
    HANDLE_W = 11         # 与 QSS 里 QSlider::handle 的 width 对齐

    def __init__(self, panel, slider, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._slider = slider
        self.ratios = []
        self.setFixedHeight(self.H)
        self.setFixedWidth(slider.width())
        # 透明于鼠标：它只是刻度，点了要落到滑块/地图上
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_ratios(self, ratios) -> None:
        self.ratios = sorted(ratios)
        self.setToolTip("共 %d 档：" % len(self.ratios)
                        + " / ".join(f"{r:g}×" for r in self.ratios))
        self.update()

    def paintEvent(self, _e) -> None:      # noqa: N802
        if not self.ratios:
            return
        span = math.log(self._panel.zmax / self._panel.zbase)
        if span <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        cur = self._panel._zoom_of(self._slider.value()) / self._panel.zbase
        near = min(self.ratios, key=lambda r: abs(math.log(cur / r)))
        x0 = self.HANDLE_W / 2.0
        usable = max(self.width() - self.HANDLE_W, 1)
        for r in self.ratios:
            x = int(round(x0 + math.log(r) / span * usable))
            pen = QPen(QColor(47, 111, 237, 240) if r == near
                       else QColor(40, 46, 56, 110))
            pen.setWidth(1)
            p.setPen(pen)
            p.drawLine(x, 0, x, self.height() - 1)
        p.end()


class ScalePanel(QFrame):
    """右上角双滑块面板。"""

    zoom_to = Signal(float)          # 拖"整体缩放"滑块 → 目标缩放
    zoom_locked = Signal(bool)       # 整体缩放的锁
    font_mul_to = Signal(float)      # 拖"字体缩放"滑块 → 字号倍率
    font_locked = Signal(bool)       # 字体缩放的锁

    TICKS = 1000

    # ★ v2.6.53：**字体倍率内部值 = 界面显示值**（用户：「能不能把内部值和显示值统一？
    #   我根本看不到内部值是多少」）。做法：让倍率**本身就从 1.0 起步**，
    #   `fbase = fmin = 1.0` ⇒ 显示 `m / 1.0` == 倍率本身 ⇒ 屏幕上是 1.0×~3.0×，
    #   拖到哪就念哪个数，**没有第二套数**。最小档仍是 1（不会冒出比 1 小的数）。
    #   ★ 整体缩放做不到这个统一：它的真实值是 0.115~8，直接显示最左端会是 0.115×
    #     （<1，用户明令禁止）⇒ 缩放仍按"最小档 = 1.00×"的比例显示。
    def __init__(self, parent=None, zmin: float = 0.115, zmax: float = 8.0,
                 fmin: float = 1.0, fmax: float = 3.0):
        super().__init__(parent)
        self.setObjectName("ScalePanel")
        self.setStyleSheet(_QSS)
        self.zmin, self.zmax = max(zmin, 1e-4), max(zmax, zmin * 1.01)
        self.fmin, self.fmax = fmin, fmax
        # ★★ v2.6.48：滑块上显示的**比例**，以"最左端 = 1"为基数重新标定。
        #   用户原话：「0.05~8，我把 0.05 作为 1 —— 这个缩放可能是 1~8、1~100、
        #   1~10，总之把现在的 0.05 作为那个最小的基数」。
        #   ⇒ 显示值 = 实际值 ÷ 最小档：整体缩放 0.05→**1.00×**、8.0→**160×**；
        #     字体倍率 0.4→**1.0×**、3.0→**7.5×**。内部数值和拖动范围一律不变。
        self.zbase = self.zmin
        self.fbase = self.fmin
        self._lz = math.log(self.zmin)
        self._hz = math.log(self.zmax)

        # ★ v2.6.43：上/右**零内边距** ⇒ 真的贴到视口右上角（配合 chrome_margin=0）
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 0, 0, 2)
        root.setSpacing(2)
        self.chrome_margin = 0       # 供 MapView._layout_chrome 读取（覆盖全局 16）
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # ---- 第一行：整体缩放 ----
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self.btn_zlock = QToolButton(self)
        self.btn_zlock.setCheckable(True)
        self.btn_zlock.setText(LOCK_OFF)
        self.btn_zlock.setToolTip("锁住当前缩放比例（滚轮不再改变它）")
        self.btn_zlock.setCursor(Qt.PointingHandCursor)      # ★ v2.6.52：可点
        self.btn_zlock.toggled.connect(self._on_zlock)
        # ★ v2.6.52：每格滚轮走 32 tick ≈ 缩放 ±14%（跟地图滚轮一格 1.15× 手感一致）
        self.sld_zoom = _WheelSlider(self, wheel_tick=32)
        self.sld_zoom.setRange(0, self.TICKS)
        self.sld_zoom.setFixedWidth(100)   # ★ v2.6.79：挪进左栏，收窄到 100 适配栏宽
        self.sld_zoom.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sld_zoom.valueChanged.connect(self._on_zoom)
        # ★ v2.6.53：滑块**正下方**挂一条档位刻度（2 的幂），并跟着重画当前档
        self.tick_zoom = _TickBar(self, self.sld_zoom, self)
        self.sld_zoom.valueChanged.connect(lambda _v: self.tick_zoom.update())
        self.lab_zoom = QLabel("1.00×", self)
        self.lab_zoom.setFixedWidth(46)
        self.lab_zoom.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        col1 = QVBoxLayout()
        col1.setSpacing(0)
        col1.setContentsMargins(0, 0, 0, 0)
        col1.addWidget(self.sld_zoom)
        col1.addWidget(self.tick_zoom)
        r1.addWidget(self.btn_zlock)
        r1.addLayout(col1)
        r1.addWidget(self.lab_zoom)
        root.addLayout(r1)

        # 档位 = 显示倍率的 2 的幂，一直翻倍到超过最大档为止
        _rr, _r, _top = [], 1.0, self.zmax / self.zbase
        while _r <= _top + 1e-9:
            _rr.append(_r)
            _r *= 2.0
        self.tick_zoom.set_ratios(_rr)

        # ---- 第二行：字体缩放 ----
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.btn_flock = QToolButton(self)
        self.btn_flock.setCheckable(True)
        self.btn_flock.setText(LOCK_OFF)
        self.btn_flock.setToolTip("锁住字号的屏幕大小（之后再缩放地图，字不跟着变）")
        self.btn_flock.setCursor(Qt.PointingHandCursor)      # ★ v2.6.52：可点
        self.btn_flock.toggled.connect(self._on_flock)
        # ★ v2.6.52：字体行程只有 1.8~3.0 ⇒ 每格 50 tick ≈ 倍率 ±0.06（约 20 格到底）
        self.sld_font = _WheelSlider(self, wheel_tick=50)
        self.sld_font.setRange(0, self.TICKS)
        self.sld_font.setFixedWidth(100)   # ★ v2.6.79：同上
        self.sld_font.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.sld_font.valueChanged.connect(self._on_font)
        self.lab_font = QLabel("1.0×", self)
        self.lab_font.setFixedWidth(46)
        self.lab_font.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r2.addWidget(self.btn_flock)
        r2.addWidget(self.sld_font)
        r2.addWidget(self.lab_font)
        root.addLayout(r2)

        self.setFixedSize(self.sizeHint())
        self._font_locked_px = None     # 锁住时的字号（由外部 set_font_locked_px 给）

    # ---------------- 内部：滑块 ↔ 数值 ----------------
    def _zoom_of(self, v: int) -> float:
        t = v / float(self.TICKS)
        return math.exp(self._lz + (self._hz - self._lz) * t)

    def _tick_of_zoom(self, s: float) -> int:
        s = min(max(s, self.zmin), self.zmax)
        t = (math.log(s) - self._lz) / max(self._hz - self._lz, 1e-9)
        return int(round(t * self.TICKS))

    def _mul_of(self, v: int) -> float:
        t = v / float(self.TICKS)
        return self.fmin + (self.fmax - self.fmin) * t

    def _tick_of_mul(self, m: float) -> int:
        m = min(max(m, self.fmin), self.fmax)
        t = (m - self.fmin) / max(self.fmax - self.fmin, 1e-9)
        return int(round(t * self.TICKS))

    # ---------------- 槽 ----------------
    def _on_zlock(self, on: bool) -> None:
        self.btn_zlock.setText(LOCK_ON if on else LOCK_OFF)
        self.zoom_locked.emit(on)

    def _on_flock(self, on: bool) -> None:
        self.btn_flock.setText(LOCK_ON if on else LOCK_OFF)
        self.font_locked.emit(on)

    def _on_zoom(self, v: int) -> None:
        s = self._zoom_of(v)
        self.lab_zoom.setText(f"{s / self.zbase:.2f}×")
        self.zoom_to.emit(s)

    def _on_font(self, v: int) -> None:
        m = self._mul_of(v)
        self.lab_font.setText(f"{m / self.fbase:.1f}×")
        self.font_mul_to.emit(m)

    # ---------------- 外部同步（不触发信号） ----------------
    def set_zoom(self, s: float) -> None:
        """把"当前缩放"同步回滑块（滚轮/适应按钮改变缩放时调用）。"""
        v = self._tick_of_zoom(s)
        if self.sld_zoom.value() != v:
            self.sld_zoom.blockSignals(True)
            self.sld_zoom.setValue(v)
            self.sld_zoom.blockSignals(False)
        self.lab_zoom.setText(f"{s / self.zbase:.2f}×")

    def set_font_mul(self, m: float) -> None:
        v = self._tick_of_mul(m)
        if self.sld_font.value() != v:
            self.sld_font.blockSignals(True)
            self.sld_font.setValue(v)
            self.sld_font.blockSignals(False)
        self.lab_font.setText(f"{m / self.fbase:.1f}×")

    def show_font_px(self, px: float) -> None:
        """锁住字号时，数值直接显示"多少像素"，更直观。"""
        self.lab_font.setText(f"{px:.0f}px")

    def font_lock_btn(self) -> QToolButton:
        return self.btn_flock

    def zoom_lock_btn(self) -> QToolButton:
        return self.btn_zlock
