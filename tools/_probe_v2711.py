# -*- coding: utf-8 -*-
"""v2.7.11 探针：七项改动的判据（**全程离屏，不弹任何窗口**）。

用户原话（v2.7.11 一条消息里的七件事）：
  ① 改为红色圈闪烁，文字不闪烁；
  ② 出入口编号「13-15」这类要显示完整（双击弹窗 / 右侧弹窗），
     但**不要动右侧详细信息输入框的长度**；
  ③ 首末班车的「＋ 添加一行」挪到「末班」右侧，不能破坏现有空间占用；
  ④ 站名默认居中，点击编辑后从左往右；
  ⑤ 线路下拉的悬浮提示去掉「已选：」；
  ⑥ 压缩「所属区」下拉宽度，让「所属线路」下拉内容显示完整；
  ⑦ 右侧弹窗没有出入口信息时不留大间距，按"只有一个出入口"留空。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QRectF, QEvent                # noqa: E402
from PySide6.QtGui import QFontMetrics, QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton       # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"   （{extra}）" if extra else ""))


app = QApplication(sys.argv)
from ui.main_window import MainWindow                         # noqa: E402
from ui.exits_editor import ExitsEditor                       # noqa: E402
from ui.timetable_editor import TimetableEditor               # noqa: E402
import ui.metro_render as MR                                  # noqa: E402

win = MainWindow()
win.show()
panel = win.info_panel
mv = win.map_view


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


pump(12)

print("===== ① 选中 = 圆点填红 + 红圈闪烁，文字不动 =====")


def red_box(sid):
    """把站点周边 80 场景单位渲染成 120×120，返回"偏红像素"的统计。"""
    it = mv.station_items[sid]
    half = 40.0 / max(mv.transform().m11(), 1e-6)
    p = it.scenePos()
    img = QImage(120, 120, QImage.Format_ARGB32)
    img.fill(Qt.white)
    pt = QPainter(img)
    mv.scene_.render(pt, QRectF(0, 0, 120, 120),
                     QRectF(p.x() - half, p.y() - half, half * 2, half * 2))
    pt.end()
    xs, ys = [], []
    for y in range(120):
        for x in range(120):
            c = QColor(img.pixel(x, y))
            if c.red() - max(c.green(), c.blue()) > 25:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0, 0
    mid = (min(ys) + max(ys)) // 2
    span = 0
    for x in range(120):
        c = QColor(img.pixel(x, mid))
        if c.red() - max(c.green(), c.blue()) > 25:
            span = max(span, x - min(xs))
    return len(xs), span


# ★ 地图本身有"偏红"的像素（线路/别的站名），所以判据一律**跟未选中时的底噪比**
n_base, _ = red_box("后瑞")
mv.select_station("后瑞", reveal=False)
pump()
it = mv.station_items["后瑞"]
n_off, _ = red_box("后瑞")           # 闪烁期间（_blink 半周）
for _ in range(80):                   # 等闪烁自己跑完（4 回合 × 280ms）
    app.processEvents()
    QTest.qWait(50)
n_on, span_on = red_box("后瑞")
ok("①-1 闪烁结束后红圈**常亮**（比划过程中更宽）",
   n_on > n_off + 20, f"闪中 {n_off} 像素 → 闪完 {n_on} 像素")
ok("①-2 圆点仍是**红色实心**（比底噪多出圆点本身）", n_on > n_base + 40,
   f"底噪 {n_base} → 选中后 {n_on}")
ok("①-3 站名**不变色**（#111827）",
   it.label.brush().color().name().lower() == MR.LABEL_COLOR_NORMAL.lower(),
   it.label.brush().color().name())
ok("①-4 站名**不闪**（透明度恒 1.0）", abs(it.label.opacity() - 1.0) < 1e-6,
   f"{it.label.opacity()}")
it.set_blink(True)
pump(2)
n_off2, _ = red_box("后瑞")
ok("①-5 闪烁「灭」半周红圈消失", n_off2 < n_on - 20, f"{n_on} → {n_off2}")
it.set_blink(False)
mv.clear_selection()
pump(2)
n_none, _ = red_box("后瑞")
ok("①-6 取消选中后回到未选中的样子", abs(n_none - n_base) < 40,
   f"底噪 {n_base} → 取消后 {n_none}")

print("\n===== ② 编号「13-15」显示完整 =====")
mv.select_station("岗厦北", reveal=False)
pump()
ee = panel.findChildren(ExitsEditor)[0]
bad = []
for tag_ed, txt_ed, tag, _x, _l in ee.rows:
    need = QFontMetrics(tag_ed.ed.font()).horizontalAdvance(tag) + 18
    if tag_ed.width() < need:
        bad.append((tag, tag_ed.width(), need))
ok("②-1 每个编号都放得下（含 13-15 / 16-18）", not bad, f"不够的：{bad}")
ok("②-2 详细信息框仍是输入框（没被降级）",
   all(not r[1].isReadOnly() for r in ee.rows))

print("\n===== ③ 首末班：按钮挪到「末班」右侧 =====")
te = TimetableEditor("工作日 · 1号线：往罗湖 首06:02 末23:47", compact=True)
te.resize(760, 400)
te.show()
pump(8)
btn = te._btn_add
ok("③-1 按钮存在", btn is not None)
hdr = btn.parentWidget() if btn else None
from PySide6.QtWidgets import QLabel                            # noqa: E402
same_row_as_manban = (hdr is not None and any(
    isinstance(c, QLabel) and c.text() == "末班" for c in hdr.findChildren(QLabel)))
ok("③-2 按钮挂在**表头行**里（跟「末班」同一个容器）", same_row_as_manban,
   f"按钮 y(相对编辑器)={btn.mapTo(te, btn.rect().topLeft()).y() if btn else '-'}")
ok("③-3 按钮在「末班」右侧", btn is not None and btn.x() > 300,
   f"按钮 x={btn.x() if btn else '-'}")
ok("③-4 按钮高度压到 ≤26px（表头那一行没被顶高）",
   btn is not None and btn.height() <= 26, f"h={btn.height() if btn else '-'}")
ok("③-5 编辑器里**没有**第二个「＋ 添加一行」按钮",
   len([b for b in te.findChildren(QPushButton) if "添加一行" in b.text()]) == 1)
te.deleteLater()

print("\n===== ④ 站名居中 / 聚焦靠左 =====")
mv.select_station("岗厦北", reveal=False)
pump()
ok("④-1 默认居中", int(panel.title.alignment()) == int(Qt.AlignCenter),
   f"alignment={int(panel.title.alignment())}")
# ★ 离屏窗口拿不到真实键盘焦点（setFocus 不一定送出 FocusIn），
#   所以直接**投递焦点事件** —— 判据要验的是事件过滤器本身
from PySide6.QtGui import QFocusEvent                            # noqa: E402
QApplication.sendEvent(panel.title, QFocusEvent(QEvent.FocusIn))
pump(4)
ok("④-2 点进去编辑时靠左", int(panel.title.alignment()) == 129,
   f"alignment={int(panel.title.alignment())}")
QApplication.sendEvent(panel.title, QFocusEvent(QEvent.FocusOut))
pump(4)
ok("④-3 失焦后回到居中", int(panel.title.alignment()) == int(Qt.AlignCenter))

print("\n===== ⑤/⑥ 线路下拉 & 所属区 =====")
ls = panel.top_lines_select
fm = QFontMetrics(ls.font())
need = fm.horizontalAdvance(ls.text()) + ls.TEXT_LEFT + ls.TEXT_RIGHT
ok("⑤-1 悬浮提示没有「已选：」前缀", not ls.toolTip().startswith("已选："),
   f"tooltip={ls.toolTip()!r}")
ok("⑥-1 线路下拉宽度够放下 4 条线路名", ls.width() >= need,
   f"宽 {ls.width()} / 需要 {need}（{ls.text()!r}）")
# ★ v2.7.12 改写：v2.7.11 把区下拉压到 80px 属于"压过头"——用户反馈
#   「区的下拉菜单『区』字没有完全显示出来」。判据改成"仍要窄（≤100）**且**
#   装得下最长选项"，两个条件一起守，防止以后再压过头或涨太宽。
_dw = panel.top_district.width()
_dneed = max(QFontMetrics(panel.top_district.font()).horizontalAdvance(
    panel.top_district.itemText(i)) for i in range(panel.top_district.count()))
ok("⑥-2 所属区下拉：仍保持窄（≤100）**且**装得下最长选项", _dw <= 100 and _dw - 40 >= _dneed,
   f"宽 {_dw} / 最长文字 {_dneed}")
row = panel.top_row
used = 12
for i in range(row.count()):
    w = row.itemAt(i).widget()
    if w is not None and not w.isHidden():
        used = max(used, w.geometry().right())
ok("⑥-3 顶部这一行**没被挤溢出**（控件都在面板内）",
   used <= panel.width(), f"最右 {used} / 面板 {panel.width()}")

print("\n===== ⑦ 空出入口不留大间距 =====")
st = json.load(open("data/stations.json", encoding="utf-8"))["stations"]
sid = next((k for k, v in st.items() if not (v.get("exits") or "").strip()), None)
mv.select_station(sid, reveal=False)
pump()
e2 = panel.findChildren(ExitsEditor)[0]
rw = e2.rows[0][1].parentWidget()
top = rw.mapTo(e2, rw.rect().topLeft()).y()
gap = e2._add_btn.mapTo(e2, e2._add_btn.rect().topLeft()).y() - (top + rw.height())
ok(f"⑦-1 空站（{sid}）只有一行、贴顶排", top == 0 and len(e2.rows) == 1,
   f"行 y={top} 行数={len(e2.rows)}")
ok("⑦-2 「出口行 → 添加按钮」之间没有大间距", gap <= 10, f"间距 {gap}px")
chip = e2.rows[0][0]
need_ph = QFontMetrics(chip.btn.font()).horizontalAdvance("编号") + 20
ok("⑦-3 空行的「编号」占位放得下（不再折成两行）", chip.width() >= need_ph,
   f"宽 {chip.width()} / 需要 {need_ph}")

print("\n===== ⑧ 变异自检：拆掉红环 ⇒ ①-1 必须变红 =====")
_orig_ring = MR.StationDotItem._paint_selected_ring
MR.StationDotItem._paint_selected_ring = lambda self, p, k: None
try:
    mv.select_station("后瑞", reveal=False)
    for _ in range(80):
        app.processEvents()
        QTest.qWait(50)
    n_noring, _ = red_box("后瑞")
    ok("⑧-1 没有红环时 ①-1 判据能分辨", n_noring < n_on - 20,
       f"有环 {n_on} → 无环 {n_noring}")
finally:
    MR.StationDotItem._paint_selected_ring = _orig_ring
mv.clear_selection()
pump(2)

print(f"\n===== 结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项：" + "、".join(FAIL))
win.close()
sys.exit(1 if FAIL else 0)
