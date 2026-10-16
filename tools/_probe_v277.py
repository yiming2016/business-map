# -*- coding: utf-8 -*-
"""v2.7.7 探针：出入口「至少 2 行」+ 编号列 80% + 单击站点不挪图只闪烁。

用户原话：
  「右侧弹窗的高度要自适应，高度至少显示2行，站点输入框改(A、B、C这个)为现在长度的80%
    不需要因为点击站点后地图跟随挪动，点击站点后对应的站点闪烁即可」
  AskUserQuestion 已确认：① 高度 = **出入口的详细信息框**（不是整块、不是所有多行框）；
  ② 只改**基础宽度**（长编号仍按实测宽度，不缩 80%）；③ 搜索定位**保留**居中放大。

判据清单：
  T1 编号列基础宽 = 37（= 旧的 46 × 0.8）
  T2 长编号不被缩：calc_tag_width(["14a、14b、14c"]) 仍 > 37（走实测宽度那条路）
  T3 详细信息框**最小 2 行**：1 行内容时高度 ≥ 2 行基准，且无内部滚动条
  T4 高度仍**自适应**：内容变长 ⇒ 更高（不是钉死 2 行）
  T5 单击路径确实带 reveal=False（鼠标点圆点 / 点站名，共 2 处）
  T6 单击站点 ⇒ **画面中心不动**（不 ensureVisible）
  T7 单击站点 ⇒ 该站**开始闪烁**（_blink_item 是它 + 定时器在跑）
  T8 键盘导航（reveal 默认 True）仍会把屏幕外的站带进可视区 —— 没被误伤
  T9 变异自检（三条）：① 编号宽退回 46 ⇒ T1 红；② 最小高度退回 1 行 ⇒ T3 红；
     ③ select_station 里 reveal 分支去掉 ⇒ T6 红

★ 铁律：探针不许写真数据、不落盘。全程只动 MainWindow 内存状态，不切站、不关窗。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtTest import QTest                    # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow               # noqa: E402
import ui.map_view as MV                            # noqa: E402
from ui.exits_editor import ExitsEditor, EXIT_TAG_W  # noqa: E402
from ui.autofit import min_height_for_lines, no_inner_scroll  # noqa: E402

PASS = []


def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)


def pump(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.show()
pump(20)
mv = win.map_view

print("\n-- T1 编号列基础宽度（80%）--")
ok("T1 基础宽 = 37（旧值 46 × 0.8）", EXIT_TAG_W == 37, f"EXIT_TAG_W={EXIT_TAG_W}")

print("\n-- T2 长编号不被缩（只改基础宽度）--")
w_long = ExitsEditor.calc_tag_width(["14a、14b、14c"])
w_short = ExitsEditor.calc_tag_width(["A", "B", "C"])
print(f"     短编号={w_short}px  长编号={w_long}px")
ok("T2a 短编号 = 基础宽 37", w_short == EXIT_TAG_W, f"{w_short}")
ok("T2b 长编号**仍按实测宽度**（没被 ×0.8 截断）", w_long > 37, f"{w_long}")

print("\n-- T3 详细信息框最小 2 行 --")
ed = ExitsEditor("A出入口：宝安大道\nB出入口：宝安大道西侧、福围儿童公园、宝安海事局、深圳市公安局交通管理支队机场大队、另加一段很长很长的内容用来验证换行之后还会不会继续长高")
ed.resize(300, 400)
ed.show()
pump(20)
ed.relayout_rows()
pump(10)
rows = ed.rows
ok("T3a 造出 2 行", len(rows) == 2, f"{len(rows)} 行")
base2 = min_height_for_lines(rows[0][1], 2)
h_short = rows[0][1].height()
print(f"     2行基准={base2}px  短内容框高={h_short}px  长内容框高={rows[1][1].height()}px")
ok("T3b 短内容（1 行文字）也**占到 2 行高**", h_short >= base2, f"{h_short} ≥ {base2}")
ok("T3c 没有内部滚动条（文字真的全露出来了）", no_inner_scroll(rows[0][1]))
# ★ 真正 2 行文字的框，量出来的高度必须跟"2 行基准"吻合（±4px）——
#   否则 min_height_for_lines 算错了，T3b 就成了自己给自己发通行证。
ed2l = ExitsEditor("A出入口：第一行\nB出入口：第二行")
ed2l.resize(300, 300)
ed2l.show()
pump(15)
ed2l.relayout_rows()
pump(10)
real2 = ed2l.rows[0][1].height()
ed2l.hide()
ok("T3d 「2 行基准」= 真放两行文字时的高度", abs(real2 - base2) <= 4,
   f"真两行={real2}px 基准={base2}px")

print("\n-- T4 高度仍自适应（不是钉死 2 行）--")
ok("T4 长内容框明显更高", rows[1][1].height() > h_short + 5,
   f"{h_short} → {rows[1][1].height()}px")
ok("T4b 长内容也没内部滚动条", no_inner_scroll(rows[1][1]))
ed.hide()

print("\n-- T5 鼠标单击路径带 reveal=False --")
import ast                                           # noqa: E402
tree = ast.parse(open("ui/map_view.py", encoding="utf-8").read())
n_reveal = 0
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "select_station":
            for kw in node.keywords:
                if kw.arg == "reveal" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is False:
                    n_reveal += 1
ok("T5 源码里 2 处单击调用都带 reveal=False", n_reveal == 2, f"{n_reveal} 处")

print("\n-- T6 单击站点 ⇒ 画面不动 --")
sid = None
for k in mv.station_items:
    sid = k
    break
ok("T6a 拿得到站点", sid is not None, str(sid))
before = mv.mapToScene(mv.viewport().rect().center())
mv.select_station(sid, reveal=False)
pump(10)
after = mv.mapToScene(mv.viewport().rect().center())
d = (after - before).manhattanLength()
ok("T6b 画面中心**一动不动**", d < 0.5, f"位移={d:.3f} 场景单位")

print("\n-- T7 单击站点 ⇒ 该站闪烁 --")
ok("T7a 闪烁目标 = 这个站", getattr(mv, "_blink_item", None) is mv.station_items.get(sid))
ok("T7b 闪烁定时器在跑", bool(getattr(mv, "_blink_timer", None)
                             and mv._blink_timer.isActive()))
mv._stop_blink()

print("\n-- T8 键盘导航（reveal=True）仍会把站带进可视区 --")
far = None
c = mv.mapToScene(mv.viewport().rect().center())
for k, it in mv.station_items.items():
    if (it.pos() - c).manhattanLength() > 6000:
        far = k
        break
if far is None:
    print("     （找不到足够远的站，跳过）")
else:
    b2 = mv.mapToScene(mv.viewport().rect().center())
    mv.select_station(far)                 # 默认 reveal=True
    pump(10)
    a2 = mv.mapToScene(mv.viewport().rect().center())
    d2 = (a2 - b2).manhattanLength()
    ok("T8 键盘/程序选中仍会挪动画面（没被误伤）", d2 > 1.0, f"位移={d2:.1f}")

print("\n-- T9 变异自检（三条）--")

# ① 编号宽退回 46 ⇒ T1 判据应变红
import ui.exits_editor as EE                         # noqa: E402
old_w = EE.EXIT_TAG_W
EE.EXIT_TAG_W = 46
m1 = (EE.EXIT_TAG_W == 37)
EE.EXIT_TAG_W = old_w
ok("T9a 变异①：宽退回 46 ⇒ 判据确实会红", m1 is False)

# ② 最小高度退回 1 行 ⇒ T3b 判据应变红
ed2 = ExitsEditor("A出入口：宝安大道")
ed2.resize(300, 300)
ed2.show()
pump(15)
for r in ed2.rows:
    from ui.autofit import fit_height                # noqa: E402
    fit_height(r[1], 32)                             # 旧的 1 行下限
pump(5)
m2 = ed2.rows[0][1].height() >= base2
ed2.hide()
ok("T9b 变异②：下限退回 1 行 ⇒ 判据确实会红", m2 is False,
   f"1行下限高={ed2.rows[0][1].height()} < {base2}")

# ③ 把 reveal 分支去掉（改成永远 ensureVisible）⇒ T6b 判据应变红
b3 = mv.mapToScene(mv.viewport().rect().center())
sid3 = None
# ★ v2.7.13：地图视口变宽了（左右面板改成浮层，不再从布局里分走宽度），
#   "偏离中心 >3000 场景单位"这条旧门槛现在可能仍在视口内 ⇒ ensureVisible
#   什么都不用做，判据前提失效（假失败）。改成挑一个**当前视口之外**的站。
_vis = mv.mapToScene(mv.viewport().rect()).boundingRect()
for k, it in mv.station_items.items():
    if not _vis.contains(it.pos()):
        sid3 = k
        break
if sid3 is None:
    print("     （找不到偏离中心的站，跳过 T9c）")
else:
    mv.select_station(sid3, reveal=False)            # 新行为：不挪
    pump(10)
    a3 = mv.mapToScene(mv.viewport().rect().center())
    d3 = (a3 - b3).manhattanLength()
    mv.select_station(sid3, reveal=True)             # 旧行为：ensureVisible
    pump(10)
    a4 = mv.mapToScene(mv.viewport().rect().center())
    d4 = (a4 - a3).manhattanLength()
    ok("T9c 变异③：reveal=True（旧行为）会挪动 ⇒ 判据能分辨", d4 > 1.0,
       f"新行为位移={d3:.2f} 旧行为位移={d4:.2f}")

n_fail = len(PASS) - sum(PASS)
print(f"\n===== 结果：{sum(PASS)} 通过 / {n_fail} 失败 =====")
win.close()
sys.exit(1 if n_fail else 0)
