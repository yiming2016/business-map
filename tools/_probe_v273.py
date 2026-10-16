# -*- coding: utf-8 -*-
"""v2.7.3 探针：

  ① 右侧面板「完全收起」：点收起后**容器一起藏掉、宽度归 0**（不再留 26px 细条），
     宽度整块还给地图；点站点 / 点展开都能原样回来。
  ② 编辑模式按钮按"有必要存在"重新删减 / 排序 / 增添：
       编辑模式 → 新建站点 → 添加模式 → 删除站点 → 保存 → 撤销 → 重做
       → 吸附到原图 → 偏差检查
     删掉的三个（自动描线 / 批量导入 / 导出）**功能不能丢** ⇒ 改挂 Ctrl+Shift 快捷键。

跑法（offscreen，绝不抢焦点）：
    METROEDITOR_NO_ACTIVATE=1 python tools/_probe_v273.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.main_window import MainWindow           # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + str(extra)) if extra else ""))


def pump(n=6):
    for _ in range(n):
        app.processEvents()


w = MainWindow()
w.resize(1480, 900)
w.show()
pump(10)

# ------------------------------------------------- ① 完全收起（0 宽，不是 26px）
print("\n-- ① 右侧面板完全收起 --")
ok("T0a 启动就是收起的", w.info_panel.isHidden() and w.info_wrap.isHidden())
ok("T0b 启动宽度=0（不是 26 细条）", w.info_wrap.width() == 0,
   f"wrapW={w.info_wrap.width()} sizes={w.splitter.sizes()}")

sid = next(iter(w.map_view.station_items))
w._on_station_clicked(sid)
pump()
ok("T1a 点站点能展开", w.info_panel.isVisible() and not w.info_wrap.isHidden())
expanded_w = w.info_wrap.width()
map_w_expanded = w.map_view.width()
ok("T1b 展开有真实宽度", expanded_w > 200, f"wrapW={expanded_w}")

w.btn_info_toggle.click()
pump()
ok("T2a 点收起 ⇒ 面板藏", w.info_panel.isHidden())
ok("T2b 点收起 ⇒ 容器也藏（真·完全收起）", w.info_wrap.isHidden())
ok("T2c 收起后宽度=0", w.info_wrap.width() == 0,
   f"wrapW={w.info_wrap.width()} sizes={w.splitter.sizes()}")
ok("T2d 宽度整块还给地图", w.map_view.width() > map_w_expanded + 100,
   f"{map_w_expanded} -> {w.map_view.width()}")
ok("T2e tooltip 变『显示站点详情面板』",
   w.btn_info_toggle.toolTip() == "显示站点详情面板")

w.btn_info_toggle.click()
pump()
ok("T3a 再点能展开", w.info_panel.isVisible() and not w.info_wrap.isHidden())
ok("T3b 展开宽度还原", abs(w.info_wrap.width() - expanded_w) <= 4,
   f"{w.info_wrap.width()} vs {expanded_w}")

w._on_map_empty_clicked()
pump()
ok("T4a 点地图空白也完全收起", w.info_wrap.isHidden() and w.info_wrap.width() == 0)

# ★ 变异自检：把"收起"退回成老的 26px 细条，判据必须立刻变红
w._on_station_clicked(sid)
pump()
w.info_panel.hide()
w.splitter.setSizes([w.splitter.sizes()[0], w.splitter.sizes()[1], 26])
pump()
ok("T5 变异（留 26px 细条）⇒ 判据必须失败",
   not (w.info_wrap.width() == 0), f"wrapW={w.info_wrap.width()}")
w._on_toggle_info_panel()
pump()

# --------------------------------------------- ② 编辑模式按钮的删减 / 排序 / 增添
print("\n-- ② 编辑模式按钮 --")
w.act_edit_mode.setChecked(True)
w._on_toggle_edit_mode(True)
pump()

tb = w.toolbar
acts = tb.actions()


def idx_text(txt, lst=None):
    for i, a in enumerate(lst if lst is not None else acts):
        if a.text() == txt:
            return i
    return None


def idx_widget(wid):
    for i, a in enumerate(acts):
        if tb.widgetForAction(a) is wid:
            return i
    return None


CHAIN = ["✎ 编辑模式", "➕ 新建站点", "✳ 添加模式", "🗑 删除站点", "💾 保存",
         "↶ 撤销", "↷ 重做", "🧲 吸附到原图", "📏 偏差检查"]
idxs = {t: idx_text(t) for t in CHAIN}
missing = [t for t, i in idxs.items() if i is None]
ok("T6a 九个按钮都在工具栏里", not missing, f"缺失={missing}")
ok("T6b 严格按定案顺序排",
   (not missing) and all(idxs[CHAIN[k]] < idxs[CHAIN[k + 1]]
                         for k in range(len(CHAIN) - 1)), str(idxs))

i_icon = idx_widget(w.map_view.icon_panel)
ok("T6c 整串在『豪宅』那一行之后",
   i_icon is not None and i_icon < idxs[CHAIN[0]], f"icon={i_icon}")

# 删掉的三个必须**不在**工具栏，但快捷键还在（功能不丢）
for txt in ("🧭 自动描线", "📥 批量导入", "📤 导出当前数据"):
    ok(f"T7 「{txt}」已不在工具栏", idx_text(txt) is None)


def win_action(txt):
    for a in w.actions():
        if a.text() == txt:
            return a
    return None


sc = {"🧭 自动描线": "Ctrl+Shift+T",
      "📥 批量导入": "Ctrl+Shift+I",
      "📤 导出当前数据": "Ctrl+Shift+E"}
for txt, ks in sc.items():
    a = win_action(txt)
    ok(f"T8 「{txt}」快捷键 {ks} 仍在（功能没丢）",
       a is not None and a.shortcut() == QKeySequence(ks),
       str(a.shortcut()) if a else "无此 action")

# 增添的「删除站点」：**面板收起时必须只提示、不弹框、不删**
# （★ offscreen 下 QMessageBox 会直接挂死探针；更要紧的是"收起时还记着上一个站"
#    ⇒ 照着删 = 盲删，所以产品侧也要求面板必须开着）
n0 = len(w.map_view.station_items)
if w.info_wrap.isHidden():
    w._on_toggle_info_panel()      # 先展开
    pump()
w.btn_info_toggle.click()          # 再收起
pump()
ok("T9a 前置：面板已收起", w.info_wrap.isHidden())
w._on_delete_current_station()
pump()
ok("T9b 面板收起时点删除 ⇒ 不删任何站（也不弹框）",
   len(w.map_view.station_items) == n0,
   f"{n0} -> {len(w.map_view.station_items)}")

# ★ 变异自检：把「保存」挪到最前，顺序判据必须变红
a_save = None
for a in acts:
    if a.text() == "💾 保存":
        a_save = a
        break
if a_save is not None:
    tb.removeAction(a_save)
    tb.insertAction(acts[0], a_save)
    acts2 = tb.actions()
    idxs2 = {t: idx_text(t, acts2) for t in CHAIN}
    seq2 = all(v is not None for v in idxs2.values()) and all(
        idxs2[CHAIN[k]] < idxs2[CHAIN[k + 1]] for k in range(len(CHAIN) - 1))
    ok("T10 变异（把保存挪到最前）⇒ 顺序判据必须失败", seq2 is False, str(idxs2))

print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：")
    for n in FAIL:
        print("   - " + n)
sys.exit(1 if FAIL else 0)
