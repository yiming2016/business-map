# -*- coding: utf-8 -*-
"""v2.7.15「看图模式 = 真的像看照片」离屏探针（offscreen，绝不弹窗）。

背景（用户实测报的）：看图模式下**一缩放就卡**。
病根：看图模式复用了给**矢量**设计的缩放链路，它的收尾 `_end_zoom_snap`
     必然调 `_restore_station_visibility()` ⇒ 383 个站点图元被 setVisible(True)
     放回来 ⇒ 看图模式当场退化成矢量。实测帧耗时 4.7ms → **31ms**。

本探针固化：
  ① 看图模式下滚轮 / 滑块 / 拖动，矢量站点**一个都不许回来**；
  ② 帧耗时必须留在"照片级"（≤12ms），且明显快于编辑模式；
  ③ 老收尾链路被守卫挡住（含**变异自检**：摘掉守卫后必须真放回来）；
  ④ 退出看图模式后矢量状态补齐（842 个图元 + 尺寸/排版重算过）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import QPointF, QPoint, Qt, QElapsedTimer      # noqa: E402
from PySide6.QtGui import QWheelEvent                              # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402

app = QApplication(sys.argv)
from ui.main_window import MainWindow                              # noqa: E402

PASS = FAIL = 0
FAILED = []


def ok(name, cond, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  ({info})" if info else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ✗ {name}  —— {info}")


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1600, 900)
win.show()
pump(20)
mv = win.map_view
win._view_autostart_done = True
mv.fit_map()
pump(15)

vp = mv.viewport()


def visible_items():
    return sum(1 for it in mv.scene_.items() if it.isVisible())


def visible_stations():
    return sum(1 for it in mv.station_items.values() if it.isVisible())


def frame_ms(n=30):
    """连续 n 次同步重绘的平均单帧耗时（ms）。"""
    t = QElapsedTimer()
    t.start()
    for _ in range(n):
        mv.viewport().repaint()
        app.processEvents()
    return t.elapsed() / n


def wheel(times=1, delta=120):
    for _ in range(times):
        ev = QWheelEvent(QPointF(vp.rect().center()), QPointF(vp.rect().center()),
                         QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                         Qt.NoModifier, Qt.ScrollBegin, False)
        QApplication.sendEvent(vp, ev)
        pump(4)
    pump(10)


n_edit = visible_items()
ms_edit = frame_ms()

print("===== ① 看图模式：进入后只剩一张照片 =====")
# 清缓存 ⇒ 走"首次烘图"这条最容易出事的路
d = win._data_dir()
for f in ("_view_image.png", "_view_image_meta.json"):
    p = os.path.join(d, f)
    if os.path.exists(p):
        os.remove(p)
t0 = time.time()
entered = win._enter_view_mode()
pump(12)
ok("①-1 首次（无缓存）能进看图模式", entered and mv._view_mode,
   f"{time.time()-t0:.1f}s")
ok("①-2 场景里只剩 1 个可见图元（那张照片）", visible_items() == 1,
   f"可见 {visible_items()}（进入前 {n_edit}）")
ok("①-3 383 个矢量站点全部藏着", visible_stations() == 0,
   f"可见 {visible_stations()}")
ms_view = frame_ms()
ok("①-4 看图模式单帧 ≤12ms（照片级）", ms_view <= 12.0, f"{ms_view:.1f} ms/帧")
ok("①-5 看图模式比编辑模式明显快", ms_view < ms_edit,
   f"看图 {ms_view:.1f} vs 编辑 {ms_edit:.1f} ms/帧")

print("===== ② 缩放：不许把矢量站点放回来（核心） =====")
s0 = mv.transform().m11()
wheel(3)
s1 = mv.transform().m11()
ok("②-1 滚轮真的改变了缩放", abs(s1 - s0) > 1e-6, f"{s0:.4f} → {s1:.4f}")
ok("②-2 滚轮 3 档后矢量站点仍然 0 个可见", visible_stations() == 0,
   f"可见 {visible_stations()}")
ok("②-3 滚轮后场景里仍只有那张照片", visible_items() == 1,
   f"可见 {visible_items()}")
ok("②-4 没进老的那套「抓位图拉伸」链路", mv._zoom_snap is None,
   f"_zoom_snap={mv._zoom_snap!r}")
ms_after = frame_ms()
ok("②-5 缩放后单帧仍是照片级（≤12ms，老路径实测 31ms）", ms_after <= 12.0,
   f"{ms_after:.1f} ms/帧")
# 滑块缩放（另一条入口）
mv.scale_panel.zoom_to.emit(3.0) if hasattr(mv.scale_panel, "zoom_to") else None
try:
    mv._on_zoom_slider(3.0)
except Exception:
    pass
pump(10)
ok("②-6 拖缩放滑块后矢量站点仍然 0 个可见", visible_stations() == 0,
   f"可见 {visible_stations()}")

print("===== ③ 拖动：同样不许放回来 =====")
h = mv.horizontalScrollBar()
v = mv.verticalScrollBar()
t = QElapsedTimer()
t.start()
for _ in range(30):
    h.setValue(h.value() + 40)
    v.setValue(v.value() + 40)
    mv.viewport().repaint()
    app.processEvents()
ms_pan = t.elapsed() / 30
ok("③-1 拖动 30 步后矢量站点仍然 0 个可见", visible_stations() == 0,
   f"可见 {visible_stations()}")
ok("③-2 拖动单步 ≤12ms", ms_pan <= 12.0, f"{ms_pan:.1f} ms/步")

print("===== ④ 变异自检：守卫真的是在挡这把刀 =====")
# 4a：直接调老收尾链路（它内部必然走 _restore_station_visibility）
mv._zoom_target = min(mv._zoom_target * 1.2, mv._zoom_max)
try:
    mv._begin_zoom_snap()
    mv._end_zoom_snap(repaint_now=False)
except Exception as e:
    print("      （老链路调用异常：", repr(e), "）")
pump(10)
ok("④-1 即使走了老的 _end_zoom_snap，站点也没被放回来",
   visible_stations() == 0, f"可见 {visible_stations()}")
# 4b：把守卫摘掉（换成"无条件恢复"），同一条链路必须真放回来 ⇒ 判据真抓得住
orig = mv._restore_station_visibility


def _bad_restore():
    for it in mv.station_items.values():
        it.setVisible(True)


mv._restore_station_visibility = _bad_restore
try:
    mv._begin_zoom_snap()
    mv._end_zoom_snap(repaint_now=False)
except Exception:
    pass
pump(6)
n_bad = visible_stations()
mv._restore_station_visibility = orig
ok("④-2 摘掉守卫后站点果然被放回来（②-2 判据确实在测守卫）", n_bad > 300,
   f"可见 {n_bad}")
# 复原到看图模式干净态
for it in mv.station_items.values():
    it.setVisible(False)
pump(4)
ok("④-3 复原后回到「只剩照片」", visible_items() == 1, f"可见 {visible_items()}")

print("===== ⑤ 红环：跟着照片一起缩放（不跟当前缩放档打架） =====")
import ast                                                          # noqa: E402
import pathlib                                                      # noqa: E402
src = pathlib.Path("ui/map_view.py").read_text(encoding="utf-8")
tree = ast.parse(src)
hit = False
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "drawForeground":
        seg = ast.get_source_segment(src, node) or ""
        hit = ("r0x / PX_PER_UNIT" in seg) or ("r0y / PX_PER_UNIT" in seg)
ok("⑤-1 看图模式红环半径按**烘图密度**算（不是按当前缩放）", hit,
   "drawForeground 里用 r0/PX_PER_UNIT")

print("===== ⑥ 退出看图模式：矢量状态要补齐 =====")
win._exit_view_mode()
pump(20)
ok("⑥-1 退出后 view_mode=False", not mv._view_mode)
ok("⑥-2 退出后 842 个图元全部回来", visible_items() == n_edit,
   f"{visible_items()} / {n_edit}")
ok("⑥-3 退出后站点尺寸重算过（不是停在烘图那一刻的旧尺寸）",
   abs(mv.station_items[next(iter(mv.station_items))]._view_scale - mv._scale) < 1e-6,
   f"item {mv.station_items[next(iter(mv.station_items))]._view_scale:.4f} "
   f"vs view {mv._scale:.4f}")

print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
if FAILED:
    print("失败项：")
    for n in FAILED:
        print("  -", n)
sys.exit(1 if FAIL else 0)
