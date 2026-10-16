# -*- coding: utf-8 -*-
"""v2.6.79 探针：①缩放双滑块进左栏底部常驻（工具栏只剩图标四开关）；
②信息面板顶部 = 图片排→站名→线路下拉(无标签)→区下拉(无标签)，collect 带images；
③编辑弹窗左上多图缩略图条；④悬浮/固定气泡多图逻辑。"""
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolBar, QLabel
from PySide6.QtCore import QPoint

app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import MainWindow  # noqa: E402
from ui.scale_panel import ScalePanel  # noqa: E402
from ui.icon_toggle_panel import IconTogglePanel  # noqa: E402
from ui.tooltip import HoverTip  # noqa: E402
from ui.edit_dialog import EditDialog  # noqa: E402
from ui.legend_panel import LegendPanel  # noqa: E402
from ui.widgets import LinesSelect  # noqa: E402

win = MainWindow()
win.show()
for _ in range(15):
    app.processEvents()

# ---------- T1：缩放面板在左栏底部、工具栏里没有它 ----------
tb = win.findChildren(QToolBar)[0]
w_in_tb = [tb.widgetForAction(a) for a in tb.actions()]
assert not any(isinstance(w, ScalePanel) for w in w_in_tb), "T1 失败：缩放面板还在工具栏里"
assert any(isinstance(w, IconTogglePanel) for w in w_in_tb), "T1 失败：图标面板丢了"
sp = win.map_view.scale_panel
par = sp.parent()
chain = []
while par is not None:
    chain.append(type(par).__name__)
    par = par.parent()
assert sp.parent() is not None and not sp.parent().inherits("QToolBar"), \
    f"T1 失败：缩放面板父级={type(sp.parent())!r}"
# 直接挂在 LegendPanel 的布局里
assert sp.parent() is win.legend_panel, \
    f"T1 失败：缩放面板应直接挂在 LegendPanel，实际 {type(sp.parent())!r}"
assert sp.isVisible(), "T1 失败：缩放面板不可见"
assert tb.height() < 90, f"T1 失败：工具栏高度 {tb.height()}px"
print(f"[T1] 缩放双滑块已入左栏底部（面板宽 {win.legend_panel.width()}px，滑块面板 {sp.width()}px），工具栏 {tb.height()}px OK")

# ---------- T2：信息面板顶部四件套 ----------
ip = win.info_panel
ip.show_station("后海")
for _ in range(10):
    app.processEvents()
assert isinstance(ip.top_lines_select, LinesSelect) and ip.top_lines_select.isVisible(), \
    "T2 失败：顶部线路下拉不可见"
assert ip.top_district.isVisible(), "T2 失败：顶部区下拉不可见"
assert ip.top_district.currentText() in ("不设置", "南山区", "福田区", "罗湖区", "宝安区", "龙华区"), \
    f"T2 失败：区下拉值异常 {ip.top_district.currentText()!r}"
# 表单里不应再有「所属线路」标签
labels = [l.text() for l in ip.findChildren(QLabel)]
assert "所属线路" not in labels, f"T2 失败：还有「所属线路」标签：{[l for l in labels if '线路' in l]}"
payload = ip._collect()
assert "images" in payload and "cover" in payload, f"T2 失败：collect 缺 images/cover：{list(payload)}"
assert isinstance(payload["images"], list), "T2 失败：images 不是列表"
print(f"[T2] 顶部 线路下拉/区下拉 无标签、collect 带 images={payload['images']} cover={payload['cover']!r} OK")

# ---------- T3：旧 cover 自动当第一张（文件存在时）；文件缺失则被死链过滤 ----------
ip.show_station("左炮台东")
for _ in range(5):
    app.processEvents()
dm = win.dm
cov = (dm.get_station("左炮台东").get("cover") or "").strip()
_exists = dm.cover_path(cov) is not None
_expected = [cov] if (cov and _exists) else []
assert ip._images == _expected, f"T3 失败：{ip._images} vs 预期 {_expected}（cover={cov!r} 存在={_exists}）"
p2 = ip._collect()
assert p2["cover"] == (_expected[0] if _expected else "") and p2["images"] == _expected, f"T3 失败：collect={p2['cover']!r}"
print(f"[T3] 旧 cover 处理（左炮台东 cover={cov!r} 文件存在={_exists} → _images={ip._images}）OK")

# ---------- T4：编辑弹窗多图条 ----------
dlg = EditDialog(station_id="左炮台东", parent=win)
for _ in range(5):
    app.processEvents()
assert hasattr(dlg, "cover_strip") and hasattr(dlg, "cover_grid"), "T4 失败：没有缩略图条"
assert len(dlg._img_entries) == (1 if cov else 0), f"T4 失败：_img_entries={dlg._img_entries}"
paths = dlg._img_paths()
assert len(paths) == len(dlg._img_entries), "T4 失败：_img_paths 与条目数不一致"
# ★ 不调 _on_add_images()：offscreen 下原生 QFileDialog 会挂住探针。
#   直接模拟"选了新图"的状态推进（不落盘、不弹窗）。
img = r"C:/software/subway/源码/assets/icons/mall_red.png"
assert os.path.exists(img), "T4 前置失败：找不到测试图片"
_n0 = len(dlg._img_entries)
dlg._img_entries.append({"name": "", "src": img})
dlg._refresh_cover_strip()
for _ in range(5):
    app.processEvents()
assert len(dlg._img_entries) == _n0 + 1, "T4 失败：追加条目失败"
assert len(dlg._img_paths()) == _n0 + 1, "T4 失败：新条目路径没进 _img_paths"
dlg._img_entries.pop()                   # 还原，别影响后续
dlg._refresh_cover_strip()
dlg.deleteLater()
print("[T4] 弹窗多图缩略图条构造 / 旧cover进条目 / 追加新图路径 OK")

# ---------- T5：悬浮/固定气泡 ----------
tip = win.tip
data = {"station_name": "测试站", "lines": ["1号线"], "description": "d" * 30,
        "is_transfer": False}
tip.show_for(QPoint(100, 100), data, [img, img, img])
assert tip.lbl_cover.isVisible() and not tip.pin_scroll.isVisible(), "T5 失败：悬浮模式应显示单张"
assert "3 张" in tip.lbl_multi.text(), f"T5 失败：多图提示={tip.lbl_multi.text()!r}"
assert not tip.pinned, "T5 失败：悬浮模式 pinned 应为 False"

tip.pin_for(QPoint(100, 100), data, [img, img, img], "测试站")
assert tip.pinned and tip.pinned_station_id == "测试站", "T5 失败：pin_for 未固定"
assert tip.pin_scroll.isVisible() and not tip.lbl_cover.isVisible(), "T5 失败：固定模式应显示滚动图带"
assert tip.pin_row.count() >= 4, f"T5 失败：图带应有3图+stretch，实际 {tip.pin_row.count()}"
assert "第" in tip.lbl_multi.text(), f"T5 失败：计数标签={tip.lbl_multi.text()!r}"
tip.unpin()
assert not tip.pinned and not tip.isVisible(), "T5 失败：unpin 未复位"
print("[T5] 悬浮单张+多图提示 / 固定图带+计数 / unpin OK")

# ---------- T6：整窗截图 ----------
win.grab().save(r"C:/software/subway/源码/_probe_v279_layout.png")
win.close()
print("ALL PASS")
