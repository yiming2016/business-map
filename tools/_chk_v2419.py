"""
v2.4.19 专项校验：
  1. 封面图标缓存 —— 同一张图只解码一次；换图（mtime 变）立刻生效
  2. 拖动夹取 —— 窗口不会被拖到屏幕外抓不回来
  3. 对齐调度合并 —— 连续 N 次 resize 不会堆出 N 个回调
  4. 对齐上限解耦 —— 封面边长恒在 [简介框高, +120] 内收敛，不会正反馈失控
  5. 弹窗置前 —— showEvent 后弹窗是可见且在最前
"""
from __future__ import annotations
import sys, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from core.data_manager import get_data_manager
from ui import edit_dialog as ED
from ui.edit_dialog import EditDialog

PASS = {"n": 0}
FAIL = {"n": 0}


def check(name, cond, extra=""):
    if cond:
        PASS["n"] += 1
        print(f"  [OK]  {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL["n"] += 1
        print(f"  [FAIL] {name}  {extra}")


def pump(ms=150):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


dm = get_data_manager()
sids = list(dm.all_stations().keys())
sid = sids[0]

# 准备一张封面图（640x640 那张在打包目录里）
covers = Path(r"C:\software\subway\软件\data\covers")
src_img = covers / "左炮台东.jpg"
have_img = src_img.exists()
print(f"测试封面图存在 = {have_img}  ({src_img})")
print()

# ============================================================
print("=== A) 封面图标缓存 ===")
# ============================================================
_real_make = ED.make_cover_icon
CALLS = {"n": 0}


def counted_make(path, size=30):
    CALLS["n"] += 1
    return _real_make(path, size)


ED.make_cover_icon = counted_make
try:
    if have_img:
        CALLS["n"] = 0
        a = ED._cached_cover_icon(src_img, 174)
        b = ED._cached_cover_icon(src_img, 174)
        c = ED._cached_cover_icon(src_img, 174)
        check("同一张图连取 3 次只解码 1 次", CALLS["n"] == 1, f"实际解码 {CALLS['n']} 次")
        check("三次拿到的是同一个对象", a is b is c and not a.isNull())

        d = ED._cached_cover_icon(src_img, 200)
        check("换尺寸会重新解码", CALLS["n"] == 2, f"累计 {CALLS['n']} 次")

        # 改 mtime 模拟"用户换了图"
        import os
        st = src_img.stat()
        os.utime(src_img, (st.st_atime + 5, st.st_mtime + 5))
        ED._cached_cover_icon(src_img, 174)
        check("mtime 变了会重新解码（换图立刻生效）", CALLS["n"] == 3, f"累计 {CALLS['n']} 次")
        os.utime(src_img, (st.st_atime, st.st_mtime))   # 改回来
    else:
        check("(跳过) 没找到测试图片", False, "封面缓存未验证")

    CALLS["n"] = 0
    e = ED._cached_cover_icon(None, 174)
    f2 = ED._cached_cover_icon(None, 174)
    check("无封面时给占位图标且被缓存", CALLS["n"] == 0 and e is f2 and not e.isNull())
finally:
    ED.make_cover_icon = _real_make

print()

# ============================================================
print("=== B) 拖动夹取：窗口不会被拖出屏幕 ===")
# ============================================================
dlg = EditDialog(station_id=sid, parent=None)
dlg.show()
pump(700)

scr = app.primaryScreen().availableGeometry()
print(f"  屏幕可用区 = ({scr.left()},{scr.top()},{scr.width()}x{scr.height()})")

for tag, pos in [
    ("左上角外 (-5000,-5000)", QPoint(-5000, -5000)),
    ("右下角外 (99999,99999)", QPoint(99999, 99999)),
    ("正上方外 (-200,-3000)",  QPoint(-200, -3000)),
    ("正常位置 (300,200)",     QPoint(300, 200)),
]:
    out = dlg._clamp_to_screen(pos)
    ok_x = scr.left() - dlg.width() + 120 <= out.x() <= scr.right() - 120
    ok_y = scr.top() <= out.y() <= scr.bottom() - 28
    check(f"夹取 {tag} → ({out.x()},{out.y()})", ok_x and ok_y,
          f"x∈[{scr.left()-dlg.width()+120},{scr.right()-120}] y∈[{scr.top()},{scr.bottom()-28}]")

print()

# ============================================================
print("=== C) 对齐/裁圆角 调度合并 ===")
# ============================================================
ALIGN = {"n": 0}
_orig_align = EditDialog._align_cover_to_desc
def cnt_align(self, *a, **kw):
    ALIGN["n"] += 1
    return _orig_align(self, *a, **kw)
EditDialog._align_cover_to_desc = cnt_align

ALIGN["n"] = 0
for i in range(10):                     # 同一帧里排 10 次
    dlg._schedule_align()
while ALIGN["n"] == 0:
    app.processEvents()
pump(150)
check("同一帧排 10 次 _schedule_align → 只执行 1 次",
      ALIGN["n"] == 1, f"实际执行 {ALIGN['n']} 次")

ALIGN["n"] = 0
for w in (650, 660, 670, 680, 690, 700):
    dlg.resize(w, 680)                  # 每次 resize 都会排一次，但本帧应合并
    app.processEvents()
pump(250)
check("连续 6 次 resize 不会各排一次（合并生效）",
      ALIGN["n"] <= 6, f"实际执行 {ALIGN['n']} 次（未合并会是 6+6=12 以上）")
EditDialog._align_cover_to_desc = _orig_align

print()

# ============================================================
print("=== D) 封面边长收敛 & 上限解耦 ===")
# ============================================================
dlg.resize(600, 680)
pump(900)
h = dlg.desc_edit.height()
bw = dlg.cover_btn.width()
lo = max(80, h)
check("封面边长 >= 简介框高（下限没被夹死）", bw >= lo, f"封面 {bw} / 简介框 {h}")
check("封面边长 <= 简介框高 + 120（上限与按钮解耦）",
      bw <= lo + 120, f"封面 {bw} <= {lo+120}")
check("封面边长 <= 600（绝对上限兜底）", bw <= 600, f"封面 {bw}")
# 底边对齐：容忍 ±3px
delta = (dlg.desc_edit.mapTo(dlg, dlg.desc_edit.rect().bottomLeft()).y()
         - dlg.cover_btn.mapTo(dlg, dlg.cover_btn.rect().bottomLeft()).y())
check("封面底边与简介框底边对齐（±3px）", abs(delta) <= 3, f"差值 {delta}px")

print()

# ============================================================
print("=== E) 弹窗置前 ===")
# ============================================================
dlg2 = EditDialog(station_id=sid, parent=None)
dlg2.show()
pump(500)
check("弹窗可见", dlg2.isVisible())
check("弹窗是活动窗口（不会被主窗口盖住）",
      dlg2.isActiveWindow(), f"activeWindow = {type(app.activeWindow()).__name__}")
check("焦点在弹窗内部（不是 None / 主窗口）",
      app.focusWidget() is not None and dlg2.isAncestorOf(app.focusWidget()),
      f"focusWidget = {type(app.focusWidget()).__name__}")

dlg2.close(); dlg.close()

print()
print("=" * 70)
print(f"通过 {PASS['n']} 项，失败 {FAIL['n']} 项")
print("全部通过 ✅" if FAIL["n"] == 0 else "有失败 ❌")
print("=" * 70)
sys.exit(1 if FAIL["n"] else 0)
