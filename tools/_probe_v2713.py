# -*- coding: utf-8 -*-
"""v2.7.13 探针：两项改动的判据（**全程离屏，不弹任何窗口**）。

用户原话（v2.7.13）：
  圈1（选 A+B）：单击左侧(图例)/右侧(站点详情面板)会立即弹窗，把弹窗改为
        **覆盖下方的图**，而不是现在把图往中间挤。
  圈2：以图中**所有元素最边界**为限制 —— 比如一个元素在最右侧，鼠标从右往左
        拖动，屏幕右侧的边界就是最右侧的这个元素（可适当保留一点空白）。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QPointF, QPoint                 # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402
from PySide6.QtTest import QTest                               # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"   （{extra}）" if extra else ""))


app = QApplication(sys.argv)
from ui.main_window import MainWindow, LEGEND_MIN_W, INFO_PANEL_MIN_W  # noqa: E402
import ui.map_view as MV                                       # noqa: E402

win = MainWindow()
win.resize(1600, 900)
win.show()
mv = win.map_view


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


pump(15)

# ================================================================ 圈1
print("===== 圈1：左右面板 = 地图之上的浮层（不再挤地图） =====")
area = win.map_area
lg = win.legend_panel
iw = win.info_wrap

ok("①-1 两个面板都挂在地图区上（parent = map_area，不再进布局）",
   lg.parent() is area and iw.parent() is area,
   f"{type(lg.parent()).__name__} / {type(iw.parent()).__name__}")
ok("①-2 地图已铺满整个地图区（没有三栏分走宽度）",
   abs(mv.width() - area.width()) <= 2, f"map {mv.width()} / area {area.width()}")

w_before = mv.width()
h_before = mv.height()
win._on_toggle_info_panel()          # 展开右侧详情面板
pump(8)
ok("①-3 ★核心：展开详情面板**地图宽度不变**（不再被挤）",
   mv.width() == w_before and mv.height() == h_before,
   f"{w_before}×{h_before} → {mv.width()}×{mv.height()}")

w2 = mv.width()
win._on_toggle_legend(False)         # 收起图例
pump(8)
ok("①-4 收起图例，地图宽度**也不变**", mv.width() == w2, f"{w2} → {mv.width()}")
win._on_toggle_legend(True)
pump(8)
ok("①-5 再展开图例，地图宽度还是不变", mv.width() == w2, f"{mv.width()}")

# 覆盖关系的**硬证据**：面板覆盖区内的点，命中的必须是面板而不是地图
probe_y = area.height() // 2
hit_l = area.childAt(QPoint(5, probe_y))
hit_r = area.childAt(QPoint(area.width() - 5, probe_y))
ok("①-6 左侧覆盖区取点 ⇒ 命中的是**图例浮层**（不是地图）",
   hit_l is not None and lg.isAncestorOf(hit_l), f"{hit_l}")
ok("①-7 右侧覆盖区取点 ⇒ 命中的是**详情浮层**（不是地图）",
   hit_r is not None and iw.isAncestorOf(hit_r), f"{hit_r}")
_mid = area.childAt(QPoint(area.width() // 2, probe_y))
ok("①-8 中间没被盖住的地方 ⇒ 仍是地图", mv.isAncestorOf(_mid) or _mid is mv, f"{_mid}")

# 拖宽把手 + 限幅
ok("①-9 两侧都有拖宽把手（宽 6px）",
   getattr(win, "legend_grip", None) is not None
   and getattr(win, "info_grip", None) is not None
   and win.legend_grip.width() == 6 and win.info_grip.width() == 6)
cap = win._overlay_width_cap()
win._set_info_w(5000)
pump(6)
ok("①-10 详情面板拖宽有**上限**", iw.width() <= cap + 2,
   f"{iw.width()} ≤ {cap}")
win._set_info_w(10)
pump(6)
ok("①-11 详情面板拖窄有**下限**", iw.width() >= INFO_PANEL_MIN_W - 2,
   f"{iw.width()} ≥ {INFO_PANEL_MIN_W}")
win._set_legend_w(10)
pump(6)
ok("①-12 图例拖窄也有下限", lg.width() >= LEGEND_MIN_W - 2,
   f"{lg.width()} ≥ {LEGEND_MIN_W}")
win._set_legend_w(200)
win._set_info_w(520)
pump(6)
# 两个浮层都开着时，地图至少还露得出 MAP_MIN_VISIBLE
vis = area.width() - lg.width() - iw.width()
ok("①-13 两栏全开时地图仍露出 ≥320px", vis >= 320,
   f"露出 {vis}px（图例 {lg.width()} + 详情 {iw.width()} / 区宽 {area.width()}）")

# ================================================================ 圈2
print("===== 圈2：拖动边界 = 所有元素的最外边界 + 一点空白 =====")
base = mv._elements_rect(force=True)
ok("②-0 元素边界可计算（判据前提）", base is not None and not base.isEmpty(),
   f"{base}")
old = getattr(mv, "_content_rect", None)
_old_txt = "无旧值" if old is None else f"{old.width():.0f}×{old.height():.0f}"
ok("②-1 用的是**元素**边界而不是旧的「站点圆心 + 460 假边距」",
   old is None or abs(base.width() - old.width()) > 1 or abs(base.height() - old.height()) > 1,
   f"元素 {base.width():.0f}×{base.height():.0f} vs 旧 {_old_txt}")


def drag(step, times=220):   # 220×80px ≈ 17600px，足够撞到边界
    for _ in range(times):
        h = mv.horizontalScrollBar()
        v = mv.verticalScrollBar()
        d = mv._pan_limit_delta(QPointF(step, step))
        h.setValue(h.value() - int(d.x()))
        v.setValue(v.value() - int(d.y()))


def vis_rect():
    """当前视口（场景坐标）。"""
    vp = mv.viewport()
    return mv.mapToScene(vp.rect()).boundingRect()


# 放到一个"大倍率"（视口远小于内容）再测 —— 用户抱怨的场景
def zoom_big():
    """放到"较大倍率"（用户抱怨的场景）：整图适配后再连放两次 4 倍。"""
    mv.fit_map()
    pump(20)
    mv._apply_zoom_transform(4.0)
    pump(25)
    mv._apply_zoom_transform(4.0)
    pump(25)


mv.fit_map()
pump(20)
s0 = mv.transform().m11()
zoom_big()
s1 = mv.transform().m11()
ok("②-2 已进入大倍率（视口远小于元素范围）", s1 > s0 * 2, f"{s0:.3f} → {s1:.3f}")

PAD = MV.PAN_ELEMENT_PAD
drag(-80)
pump(10)
r = vis_rect()
ok("②-3 往右下拖到底：**视口右边**不超出最右元素 + 空白",
   r.right() <= base.right() + PAD + 3, f"视口右 {r.right():.0f} ≤ {base.right() + PAD:.0f}")
ok("②-4 视口**下边**不超出最下元素 + 空白",
   r.bottom() <= base.bottom() + PAD + 3, f"视口下 {r.bottom():.0f} ≤ {base.bottom() + PAD:.0f}")
ok("②-5 ★ 拖到底时视口**贴着**边界（不是停在半路）",
   abs(r.right() - (base.right() + PAD)) < 8 and abs(r.bottom() - (base.bottom() + PAD)) < 8,
   f"差 {r.right() - base.right() - PAD:.1f} / {r.bottom() - base.bottom() - PAD:.1f}")

drag(80)
pump(10)
r2 = vis_rect()
ok("②-6 往左上拖到底：视口**左边**不越过最左元素 - 空白",
   r2.left() >= base.left() - PAD - 3, f"视口左 {r2.left():.0f} ≥ {base.left() - PAD:.0f}")
ok("②-7 视口**上边**不越过最上元素 - 空白",
   r2.top() >= base.top() - PAD - 3, f"视口上 {r2.top():.0f} ≥ {base.top() - PAD:.0f}")

# ★★ 变异自检：把留白放大到 3000，必须真能拖得更远（证明夹的是本轮判据）
MV.PAN_ELEMENT_PAD = 3000.0
zoom_big()
c0 = mv.mapToScene(mv.viewport().rect().center())
drag(-80)
pump(10)
loose = mv.mapToScene(mv.viewport().rect().center()).x() - c0.x()
MV.PAN_ELEMENT_PAD = PAD
zoom_big()
c1 = mv.mapToScene(mv.viewport().rect().center())
drag(-80)
pump(10)
tight = mv.mapToScene(mv.viewport().rect().center()).x() - c1.x()
ok("②-8 变异自检：留白放大后**确实能拖更远**（证明夹的是本轮限制）",
   loose > tight + 200, f"紧 {tight:.0f} → 松 {loose:.0f} 场景单位")

# 缩到最小时（视口 ≥ 内容）应居中，而不是被卡在角落
mv.fit_map()
pump(20)
rc = vis_rect()
bcx = (base.left() + base.right()) / 2.0
ok("②-9 缩到整图时视口**居中**于元素（视口比内容大时两侧不可能同时贴边）",
   abs((rc.left() + rc.right()) / 2.0 - bcx) < max((rc.width() - base.width()) / 2.0, 30),
   f"视口中心 {(rc.left() + rc.right()) / 2:.0f} vs 元素中心 {bcx:.0f}")

print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
