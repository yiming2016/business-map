# -*- coding: utf-8 -*-
"""v2.7.2 探针：工具栏重排 + 两个按钮换上软件 logo

  ① 「显示/隐藏左侧线路图例」按钮 ⇒ 图标 = 软件自己的 logo（assets/logo.png）
  ② 右侧详情面板的收起按钮 ⇒ 也在主工具栏**最右**，同样用 logo 图（不再写 « / »）
  ③ 「编辑模式」挪到「豪宅」那一行（icon_panel）**之后**
  ④ 编辑类按钮依次排在豪宅后面：
       编辑模式 → 新建站点 → 添加模式 → 保存 → 自动描线 → 偏差检查
       → 吸附到原图 → 撤销 → 重做 → 批量导入
  ⑤ 打开编辑模式后「保存 (Ctrl+S)」改叫「保存」（快捷键 Ctrl+S 仍在）

跑法（offscreen，绝不抢焦点）：
    METROEDITOR_NO_ACTIVATE=1 python tools/_probe_v272.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from core.data_manager import _frozen_assets_dir          # noqa: E402
from ui.main_window import MainWindow, _logo_icon         # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + str(extra)) if extra else ""))


w = MainWindow()
w.resize(1480, 900)
w.show()
for _ in range(6):
    app.processEvents()

tb = w.toolbar

# ---------------------------------------------------------------- ①② logo
LOGO = os.path.join(str(_frozen_assets_dir()), "logo.png")
ok("T0a assets/logo.png 存在", os.path.isfile(LOGO), LOGO)

ref = QIcon(LOGO).pixmap(22, 22).toImage()


def same_logo(btn):
    """按钮上的图 == logo.png 渲染出来的图（像素级相等才算真换上了）"""
    ic = btn.icon()
    if ic.isNull():
        return False, "icon is null"
    img = ic.pixmap(22, 22).toImage()
    if img.isNull() or img.size().width() < 8:
        return False, "pixmap %s" % (img.size(),)
    return img == ref, "size=%s" % (img.size(),)


b1, why1 = same_logo(w.btn_legend_toggle)
ok("T1a 图例开关按钮 = 软件 logo 图", b1, why1)
ok("T1b 图例开关按钮不再写文字", w.btn_legend_toggle.text() == "",
   repr(w.btn_legend_toggle.text()))
ok("T1c 图例开关按钮仍是『显示/隐藏左侧线路图例』",
   w.btn_legend_toggle.toolTip() == "显示/隐藏左侧线路图例",
   repr(w.btn_legend_toggle.toolTip()))

b2, why2 = same_logo(w.btn_info_toggle)
ok("T2a 收起按钮 = 软件 logo 图", b2, why2)
ok("T2b 收起按钮不再写 « / »", w.btn_info_toggle.text() == "",
   repr(w.btn_info_toggle.text()))
ok("T2c 收起按钮 tooltip 随状态变",
   w.btn_info_toggle.toolTip() == "显示站点详情面板",
   repr(w.btn_info_toggle.toolTip()))
w._on_toggle_info_panel()
app.processEvents()
ok("T2d 点它仍能展开右侧面板", w.info_panel.isVisible() is True)
ok("T2e 展开后 tooltip 反过来",
   w.btn_info_toggle.toolTip() == "隐藏站点详情面板",
   repr(w.btn_info_toggle.toolTip()))
w._on_toggle_info_panel()
app.processEvents()

# ------------------------------------------------------- ③④ 工具栏顺序
acts = tb.actions()


def idx_text(txt):
    for i, a in enumerate(acts):
        if a.text() == txt:
            return i
    return None


def idx_widget(wid):
    for i, a in enumerate(acts):
        if tb.widgetForAction(a) is wid:
            return i
    return None


i_icon = idx_widget(w.map_view.icon_panel)      # 「豪宅」那一行
i_btn = idx_widget(w.btn_info_toggle)           # 收起按钮
ok("T3a icon_panel(豪宅) 在工具栏里", i_icon is not None, str(i_icon))
ok("T3b 收起按钮在工具栏最右", i_btn == len(acts) - 1,
   f"btn={i_btn} 总数={len(acts)}")

# ★ v2.7.3：编辑模式按钮又重新删减/排序过一次 —— 删了 自动描线/批量导入/导出
#   （改挂 Ctrl+Shift 快捷键），增添了 删除站点。顺序以**当前定案**为准。
CHAIN = ["✎ 编辑模式", "➕ 新建站点", "✳ 添加模式", "🗑 删除站点", "💾 保存",
         "↶ 撤销", "↷ 重做", "🧲 吸附到原图", "📏 偏差检查"]
idxs = {t: idx_text(t) for t in CHAIN}
missing = [t for t, i in idxs.items() if i is None]
ok("T4a 九个按钮都在工具栏里", not missing, f"缺失={missing}")

seq_ok = (not missing) and all(idxs[CHAIN[k]] < idxs[CHAIN[k + 1]]
                               for k in range(len(CHAIN) - 1))
ok("T4b 十个按钮严格按用户给的顺序排", seq_ok, str(idxs))

after_ok = (not missing) and i_icon is not None and i_icon < idxs[CHAIN[0]]
ok("T4c 整串都在『豪宅』那一行之后", after_ok, f"icon={i_icon} 编辑模式={idxs.get(CHAIN[0])}")

# ★ 变异自检：把「保存」挪到最前面，判据必须立刻变红（证明判据真在岗）
a_trace = None
for a in acts:
    if a.text() == "💾 保存":
        a_trace = a
        break
if a_trace is not None:
    tb.removeAction(a_trace)
    tb.insertAction(acts[0], a_trace)
    acts2 = tb.actions()


    def idx_text2(txt, lst):
        for i, a in enumerate(lst):
            if a.text() == txt:
                return i
        return None

    idxs2 = {t: idx_text2(t, acts2) for t in CHAIN}
    seq2_ok = all(v is not None for v in idxs2.values()) and all(
        idxs2[CHAIN[k]] < idxs2[CHAIN[k + 1]] for k in range(len(CHAIN) - 1))
    ok("T4d 变异（把保存挪到最前）⇒ 判据必须失败", seq2_ok is False, str(idxs2))
    # 还原：插回「删除站点」之后、撤销之前
    #   ★ insertAction(before, act) 是插在 **before 之前** ⇒ 要插到删除站点后面，
    #     得拿它**后面那一个**（撤销）当锚点。拿删除站点当锚点会插到它前面 ⇒ 顺序又错。
    tb.removeAction(a_trace)
    tb.insertAction(acts[idxs["↶ 撤销"]], a_trace)
    acts = tb.actions()
    idxs = {t: idx_text(t) for t in CHAIN}
    ok("T4e 还原后顺序仍正确",
       all(idxs[CHAIN[k]] < idxs[CHAIN[k + 1]] for k in range(len(CHAIN) - 1)), str(idxs))

# ------------------------------------------------------------- ⑤ 保存改名
act_save = None
for a in tb.actions():
    if a.text().startswith("💾"):
        act_save = a
        break
ok("T5a 保存按钮文字 = 「💾 保存」（不含 Ctrl+S）",
   act_save is not None and act_save.text() == "💾 保存",
   repr(act_save.text() if act_save else None))
ok("T5b Ctrl+S 快捷键仍然绑着",
   act_save is not None and act_save.shortcut() == QKeySequence("Ctrl+S"),
   str(act_save.shortcut()) if act_save else "-")

# 编辑模式开关一开，这批按钮要真显示出来（改名不能把按钮改没了）
ok("T5c 默认全藏（编辑模式关）", all(not a.isVisible() for a in w._edit_actions))
w.act_edit_mode.setChecked(True)
w._on_toggle_edit_mode(True)
app.processEvents()
ok("T5d 开编辑模式后全部显示", all(a.isVisible() for a in w._edit_actions),
   f"共 {len(w._edit_actions)} 个")
ok("T5e 保存按钮在编辑模式里可见", act_save is not None and act_save.isVisible())

print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：")
    for n in FAIL:
        print("   - " + n)
sys.exit(1 if FAIL else 0)
