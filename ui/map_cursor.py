# -*- coding: utf-8 -*-
"""
ui/map_cursor.py
================
地图的**自定义光标**：极简圆点（v2.6.13 换掉 Qt 系统自带的手掌）。

为什么单独一个文件：光标是"画出来的位图"，跟线路/站点的场景绘制没关系，
混进 `metro_render.py` 只会让那个已经很大的模块更难读。

用户原话（两轮才定下来）：
    「可以把抓手换成其他风格吗？比如说符合现代主题的一个圆圈或什么类型」
    → 第一版给了「圆环 + 圆心」→ 「我不喜欢这个样子，还有其他选择吗」
    → 给了 8 种对比图 → 用户选 **E 极简圆点** + 「收敛一点」
⇒ 定型：**极简圆点**（Figma 的 pointer 思路 —— 不抢画面，只在需要时
   告诉你"点在哪"），整体缩到上一版的 **~60%**。
   · 静止：**只有一个小实心圆点**（r=3.4 ⇒ 直径 6.8px），不画环
   · 拖动：圆点**变小**（3.4→2.6）+ 外面**浮出一圈细环**（r=6.6）
     —— "捏住了"的收缩感；整体直径 13.2px ≈ 上一版 22px 的 60%
   · 站点上仍然是系统的 `PointingHandCursor`（手指 = 可点击，是通用语义，别换）。

★ 三个**必须实测过**的坑（都是想当然会写错的地方）：
  1. ★★ `QCursor(pixmap)` 的默认热点 **在有 devicePixelRatio 时是错的**：
     实测 `box=32, dpr=2` 时 pixmap 是 64×64，默认 hotspot 却是 **(16,16)**
     —— 它按"逻辑尺寸/2"算，却当设备像素用 ⇒ 热点落在左上角 1/4 处，
     光标指的位置和画出来的圆圈差 16px。**必须显式给设备像素的一半**。
  2. 位图按 **2 倍**画再 `setDevicePixelRatio(2)`：用户这台机 dpr=1.5，
     只画 32×32 会被放大到 48×48 ⇒ 圆环边缘发虚。
  3. 圆环外面要描一圈**半透明白**（`HALO_W`）：地图是彩色的，
     深色圆环压在红/绿线路上会糊掉，白边保证在任何底色上都看得清。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen, QPixmap

# 光标的**逻辑**尺寸（Windows 标准光标就是 32×32）
BOX = 32
DPR = 2                  # 位图按 2 倍画，高 DPI 下才不发虚

RING_COLOR = "#1F2937"   # 与站名深色 #111827 同系，但稍柔和一点
HALO_COLOR = QColor(255, 255, 255, 232)
# 白色外描边宽度（压在彩色线路上也看得清）。
# ★ 别调大：halo 是**描在深色环两侧**的，实测 3.2 时非透明像素占了画布的
#   **68%**，视觉上变成一个粗白圈；1.8 时是可控的一圈细白边。
HALO_W = 1.5

# 静止态 / 拖动态的形状参数（逻辑像素，圆心在 BOX/2）
# ★ 顺序是 (圆心半径, 外圈细环半径, 环线宽)
#   —— 与「圆环+圆心」那版的 (环半径, 环线宽, 圆心半径) **不一样**，
#      改回旧画法时必须连本文件的 `paint_shape` 一起改，别只换数字。
OPEN = (3.4, 0.0, 0.0)       # 静止：只有一个点（ring_r=0 ⇒ 不画环）
DRAG = (2.6, 6.6, 1.4)       # 拖动：点变小 + 外面浮出一圈细环


def paint_shape(p: QPainter, shape) -> None:
    """把光标形状画到 painter **当前坐标系的原点**为中心（量纲 = 逻辑像素）。

    ★★ 形状绘制**只此一份**：真光标位图（`_paint`）和验收预览图都调它。
       预览图如果自己另写一套画法，看到的就不是真光标
       （v2.6.12 第一版预览就是靠 `QPixmap.scaled()` 缩位图，
        位图带 devicePixelRatio=2，缩完画出来只剩残缺的一段弧 —— 白画）。

    形状 = **中心圆点**（任何状态都画）+ **外圈细环**（只有拖动态画）。
    """
    core_r, ring_r, ring_w = shape
    # ① 外圈细环（静止态 ring_r = 0，直接跳过）
    if ring_r > 0.1:
        p.setPen(QPen(HALO_COLOR, ring_w + 2 * HALO_W))   # 白描边先垫底
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), ring_r, ring_r)
        p.setPen(QPen(QColor(RING_COLOR), ring_w))
        p.drawEllipse(QPointF(0, 0), ring_r, ring_r)
    # ② 中心圆点：光标"点在哪"全靠它，白色外圈保证任何底色上都看得见
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(HALO_COLOR))
    p.drawEllipse(QPointF(0, 0), core_r + HALO_W, core_r + HALO_W)
    p.setBrush(QBrush(QColor(RING_COLOR)))
    p.drawEllipse(QPointF(0, 0), core_r, core_r)


def _paint(shape) -> QPixmap:
    """画一张光标位图（透明底）。所有尺寸都是**逻辑像素**。"""
    pm = QPixmap(int(BOX * DPR), int(BOX * DPR))
    pm.setDevicePixelRatio(DPR)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(DPR, DPR)
    p.translate(BOX / 2.0, BOX / 2.0)
    paint_shape(p, shape)
    p.end()
    return pm


def make_cursor(shape) -> QCursor:
    """`OPEN` / `DRAG` → QCursor。

    ★★ 热点**必须显式给设备像素的一半**（`BOX*DPR/2`）。
       默认 `QCursor(pm)` 的 (-1,-1) 在 dpr=2 时会算成 (16,16)，
       而位图是 64×64 ⇒ 热点跑到左上角 1/4 处（实测确认）。
    """
    hot = int(BOX * DPR / 2)
    return QCursor(_paint(shape), hot, hot)


# 模块级缓存：光标对象要反复 setCursor，别每次重画
_CACHE: dict = {}


def cursor(kind: str) -> QCursor:
    """取光标对象：`"open"`（可拖动）/ `"drag"`（正在拖）。"""
    shape = DRAG if kind == "drag" else OPEN
    if kind not in _CACHE:
        _CACHE[kind] = make_cursor(shape)
    return _CACHE[kind]


def pixmap_of(kind: str) -> QPixmap:
    """取光标位图（**回归测试用**：要能数出"确实画上了东西"）。"""
    return cursor(kind).pixmap()
