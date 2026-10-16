# -*- coding: utf-8 -*-
"""v2.6.76 探针：豪宅图标/数据 + 标签行自动换行（>3 组不丢）。"""
import json
import os
import sys

sys.path.insert(0, r"C:/software/subway/源码")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

# ---------- P1：icon_pixmap 对 mansion_red 用的是 PNG（非占位色块） ----------
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import ui.metro_render as MR  # noqa: E402
from ui.metro_render import icon_pixmap  # noqa: E402

ICON = Path(r"C:/software/subway/源码/assets/icons/mansion_red.png")


def render_red():
    MR._ICON_PM_CACHE.clear()
    return icon_pixmap("mansion_red", 48).toImage()


bak = ICON.with_name("mansion_red.png._probe_bak")
if bak.exists():                          # 上次半途残留 → 先恢复
    shutil.move(str(bak), str(ICON))
try:
    shutil.move(str(ICON), str(bak))
    img_ph = render_red()                 # 无 PNG → 占位色块
finally:
    if bak.exists():
        shutil.move(str(bak), str(ICON))
img_png = render_red()                    # 有 PNG → 真图标
MR._ICON_PM_CACHE.clear()

diff = sum(1 for y in range(0, 48, 4) for x in range(0, 48, 4)
           if img_ph.pixelColor(x, y) != img_png.pixelColor(x, y))
assert diff > 0, f"P1 失败：占位与 PNG 渲染完全相同（diff={diff}）"
print(f"[P1] mansion_red 用 PNG 渲染 OK（与占位差异采样点={diff}）")

# ---------- P2：数据侧豪宅标签已应用（直接读数据文件） ----------
import json  # noqa: E402

DATA = Path(r"C:/software/subway/源码/data/stations.json")
doc = json.loads(DATA.read_text(encoding="utf-8"))
stations = doc["stations"]
hh = stations["后海"]
tags = hh.get("tags") or []
m = [t for t in tags if str(t.get("icon", "")).startswith("mansion_")]
assert m and m[0]["icon"] == "mansion_red" and "深圳湾悦府" in m[0]["text"],     f"P2 失败：后海 mansion 组={m}"
n = sum(1 for st in stations.values()
        for t in (st.get("tags") or [])
        if str(t.get("icon", "")).startswith("mansion_"))
assert n >= 57, f"P2 失败：mansion 组总数={n}"
print(f"[P2] 后海 mansion_red·深圳湾悦府 OK；全库 mansion 组 = {n}")

# ---------- P3：弹窗 4 组 → 两行 6 槽，collect 保住 4 组 ----------
from ui.main_window import MainWindow  # noqa: E402
from ui.edit_dialog import EditDialog, TAG_SLOT_COUNT  # noqa: E402

win = MainWindow()
win.show()
app.processEvents()

d = EditDialog("深圳北站", parent=win)
app.processEvents()
n_sz = len(win.dm.all_stations()["深圳北站"].get("tags") or [])
assert n_sz == 4, f"P3 前提失败：深圳北站 tags={n_sz}"
assert len(d._tag_btns) == 2 * TAG_SLOT_COUNT,     f"P3 失败：槽位数={len(d._tag_btns)} 应为 6"
tw = d._widgets["tags"]
assert tw.layout().count() == 2,     f"P3 失败：标签行 layout().count()={tw.layout().count()} 应为 2 行"
icons = list(d._tag_icons)
assert icons[:4] == ["hsr", "mall_green", "hotel_purple", "mansion_purple"],     f"P3 失败：回填 icons={icons}"
print(f"[P3] 深圳北站 4 组 → 6 槽两行，回填 {icons[:4]} OK")

out = d._collect_tags()
assert len(out) == 4, f"P3 失败：collect 丢组 → {out}"
assert out[3]["icon"] == "mansion_purple" and out[3]["text"] == "莱蒙水榭春天",     f"P3 失败：collect[3]={out[3]}"
print("[P3b] _collect_tags 4 组全保留 OK")
d.deleteLater()

# ---------- P4：豪宅含义 tooltip ----------
from ui.edit_dialog import _icon_tooltip  # noqa: E402

t = _icon_tooltip("mansion_red")
assert "顶奢标杆级" in t and "15万" in t, f"P4 失败：{t!r}"
print(f"[P4] 豪宅 tooltip = {t!r} OK")

app.processEvents()
print("ALL PASS")
