# -*- coding: utf-8 -*-
"""v2.7.29 探针：拖动限制改成按**可见区**算（左右各自躲开侧边面板）。

用户原话：「拖动留白很不理想，设置成 400 依旧会被覆盖很多范围」「我想把左侧留白
和右侧留白距离分开算」⇒ 点选"自动跟随面板 + 一个余量"、"覆盖 = 被左右浮层面板盖住"。

病根：以前 _pan_limit_delta 拿的是**整个视口宽度** vw，元素可以一直拖到窗口边缘，
而窗口右（左）那一条正好被「站点详情」/ 线路面板压着 ⇒ 站点跑到面板底下。
现在改成：限制作用在"可见区"（左右各扣掉那侧浮层盖住的宽度）上，用户那个
"拖动余量"是在它之外**再**多放开的距离 ⇒ 左右天然分开，不用填两个数。

判据（都拖到拉不动为止，再看元素最边缘落在屏幕的哪个像素）：
  ① 无面板时拖到右极限 ⇒ 元素最右点贴住窗口右边缘（误差 ≤ pad）
  ② 右侧压 300px 面板时拖到右极限 ⇒ 元素最右点**退到面板左边以外**
  ③ 左侧压 240px 面板时拖到左极限 ⇒ 元素最左点退到面板右边以外
  ④ ★变异自检：把拖动余量放大到 1000 ⇒ ②③ 里"元素确实贴到极限"那条失效
     （证明判据真在读限制，不是因为内容本来就短）
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from PySide6.QtCore import QPointF, QPoint                      # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402
from PySide6.QtTest import QTest                               # noqa: E402

app = QApplication(sys.argv)
from ui.main_window import MainWindow                          # noqa: E402

FAILS = []
N_OK = 0


def ok(name, cond, info=""):
    global N_OK
    if cond:
        N_OK += 1
        print(f"  [OK] {name}" + (f"  —— {info}" if info else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  —— {info}" if info else ""))


def pump(n=10):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(25)
mv = win.map_view

# 放大到"内容明显比可见区宽"—— 否则左右同时满足 ⇒ 直接居中，测不出拖动限制
mv.scale(3.0, 3.0)
mv._scale = mv.transform().m11()
mv._refresh_scene_rect()
pump(10)

vp = mv.viewport()
VW = vp.width()


def drag(dx_total, dy_total=0.0, steps=80):
    """反复调用一次拖动的夹取，并真的滚动视口，直到拉不动为止。

    ★ 符号照抄 mouseMoveEvent 里的真用法：`h.setValue(h.value() - int(d.x()))`
      （别自创符号，否则拖的是反方向，看着"没动"其实是拖错了边）。
      delta.x() > 0 = 内容往右走（视口左边界减小）＝ 去够右边界。
    """
    sx, sy = dx_total / steps, dy_total / steps
    for _ in range(steps):
        d = mv._pan_limit_delta(QPointF(sx, sy))
        if abs(d.x()) < 0.5 and abs(d.y()) < 0.5:
            break
        hsb, vsb = mv.horizontalScrollBar(), mv.verticalScrollBar()
        hsb.setValue(hsb.value() - int(d.x()))
        vsb.setValue(vsb.value() - int(d.y()))
        app.processEvents()
        # ★ 必须跟着放大 sceneRect：滚动条 range 由它决定，不刷新就只能滚到
        #   上一次范围的最边上，"拖到一半就走不动了"（判据因此假失败）。
        mv._refresh_scene_rect()
    pump(4)


def edge_x(side):
    """元素最左 / 最右点在屏幕上的 x（px）。"""
    base = mv._elements_rect()
    left_scene = mv.mapToScene(QPoint(0, 0)).x()
    s = mv._scale
    return (base.right() - left_scene) * s if side == "r" \
        else (base.left() - left_scene) * s


def pad_px():
    return mv.pan_pad() * mv._scale


# ---- ① 无面板：元素可以贴到窗口右边缘 ----
mv.set_view_insets(0, 0)
mv.set_pan_pad(24)
drag(-6000)
pump(6)
x1 = edge_x("r")
ok("① 无面板拖到右极限 ⇒ 元素最右点贴到窗口右边缘",
   VW - pad_px() - 6 <= x1 <= VW + 6,
   f"元素右端 x={x1:.1f} 视口宽={VW} 余量={pad_px():.1f}")

# ---- ② 右侧压一块面板：元素必须退到面板之外 ----
RW = 300
mv.set_view_insets(0, RW)
drag(-6000)
pump(6)
x2 = edge_x("r")
limit2 = VW - RW + 6
ok("② 右侧有 300px 面板 ⇒ 元素最右点退到面板左边以外",
   x2 <= limit2, f"元素右端 x={x2:.1f} 允许 ≤ {limit2:.1f}")
ok("②b 且确实拖到了极限（不是内容本来就短）",
   x2 >= limit2 - pad_px() - 8,
   f"{x2:.1f} ≥ {limit2 - pad_px() - 8:.1f}")

# ---- ③ 左侧压一块面板：对称地成立 ----
LW = 240
mv.set_view_insets(LW, 0)
drag(6000)
pump(6)
x3 = edge_x("l")
ok("③ 左侧有 240px 面板 ⇒ 元素最左点退到面板右边以外",
   x3 >= LW - 6, f"元素左端 x={x3:.1f} 要求 ≥ {LW - 6}")
ok("③b 且确实拖到了极限（不是内容本来就短）",
   x3 <= LW + pad_px() + 8, f"{x3:.1f} ≤ {LW + pad_px() + 8:.1f}")

# ---- ④ ★变异自检：假装没看见右侧面板（= 改回按整个视口算的老写法）----
#   只要 _inset_r 归零，限制就会退化成旧行为 ⇒ 元素能一直贴到窗口边缘，
#   正好落进面板区 ⇒ ② 的判据必须失效。证明判据真的在读"可见区"，碰巧过不了。
mv.set_view_insets(0, 0)
drag(-6000)
pump(6)
x4 = edge_x("r")
ok("④ ★变异自检：忽略面板宽度 ⇒ 元素贴到窗口边、钻进面板区（② 判据失效）",
   x4 > VW - RW + 6, f"元素右端 x={x4:.1f} 面板左沿={VW - RW}")

print(f"\n==== v2.7.29 探针：{N_OK} 通过 / {len(FAILS)} 失败 ====")
for f in FAILS:
    print("   -", f)
sys.exit(1 if FAILS else 0)
