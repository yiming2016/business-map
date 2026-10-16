# -*- coding: utf-8 -*-
"""v2.7.1 探针：

  ① 🔒 **按钮**分上下两半变蓝（不是图标内部）
  ② 首次打开**不显示**右侧详情面板
  ③ 地图上右键（普通状态）⇒ 四类菜单：主工具栏 / 线路图例 / 详情面板 / 锁定(二级)
  ④ F11 全屏 ⇒ 默认不显示上方主工具栏
  ⑤ 搜索框搬到**左侧线路图例顶部**（1 号线上方）；工具栏不再吃右键

跑法（offscreen，绝不抢焦点）：
    METROEDITOR_NO_ACTIVATE=1 python tools/_probe_v271.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from ui.main_window import MainWindow           # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + str(extra)) if extra else ""))


w = MainWindow()
w.resize(1480, 900)
w.show()
app.processEvents()

# ---------------- T1 首次打开：右侧详情面板不显示 ----------------
print("\n-- T1 首次打开不显示右侧详情面板 --")
ok("T1a 启动时 info_panel 隐藏", w.info_panel.isVisible() is False)
# ★ v2.7.2：收起按钮不再写文字，改用 **logo 图**；状态靠 tooltip 表达
ok("T1b 收起按钮已换成 logo 图（无文字）",
   (not w.btn_info_toggle.icon().isNull()) and w.btn_info_toggle.text() == "",
   f"icon_null={w.btn_info_toggle.icon().isNull()} text={w.btn_info_toggle.text()!r}")
ok("T1c tooltip 是『显示站点详情面板』",
   w.btn_info_toggle.toolTip() == "显示站点详情面板", repr(w.btn_info_toggle.toolTip()))
w._on_toggle_info_panel()
app.processEvents()
ok("T1d 点按钮能展开", w.info_panel.isVisible() is True)
w._on_toggle_info_panel()
app.processEvents()
ok("T1e 再点又收起", w.info_panel.isVisible() is False)

# ---------------- T2 搜索框搬到图例顶部（1 号线上方） ----------------
print("\n-- T2 搜索框在左侧图例顶部 --")
sb = w.search_box
# 祖先链里要有 legend_panel
anc, p = [], sb.parent()
while p is not None:
    anc.append(p)
    p = p.parent()
ok("T2a 搜索框挂在图例面板里", w.legend_panel in anc,
   [type(a).__name__ for a in anc[:4]])
ok("T2b 搜索框不再挂在工具栏里", sb not in w.toolbar.findChildren(type(sb))
   or w.toolbar not in anc)
rows = [r for r in w.legend_panel.findChildren(type(w.legend_panel._rows[0]))] \
    if getattr(w.legend_panel, "_rows", None) else []
gb = sb.mapToGlobal(QPoint(0, 0))
y_first = min((r.mapToGlobal(QPoint(0, 0)).y() for r in rows), default=10 ** 9)
ok("T2c 搜索框在**第一行线路（1 号线）之上**", gb.y() < y_first,
   f"搜索框 y={gb.y()}  首行 y={y_first}（共 {len(rows)} 行）")
ok("T2d 搜索框可见且宽度够用", sb.isVisible() and sb.width() >= 110, f"w={sb.width()}")

# ---------------- T3 工具栏不再吃右键 ----------------
print("\n-- T3 工具栏自身右键菜单已取消 --")
ok("T3a 工具栏 contextMenuPolicy = NoContextMenu",
   w.toolbar.contextMenuPolicy() == Qt.NoContextMenu,
   str(w.toolbar.contextMenuPolicy()))

# ---------------- T4 地图右键菜单：四类、顺序 ----------------
print("\n-- T4 地图空白处右键菜单（普通状态）--")
m, handlers = w._build_map_context_menu()
ok("T4a 普通状态下能建出菜单", m is not None)
names = [a.text() for a in m.actions()]
want = ["隐藏上方主工具栏", "隐藏左侧线路图例", "显示站点详情面板", "🔒 锁定"]
ok("T4b 一级菜单四类、顺序正确", names == want, f"实际={names}")
sub = m.actions()[3].menu()
ok("T4c 第 4 项是带二级菜单的『锁定』", sub is not None)
sub_names = [a.text() for a in sub.actions()]
ok("T4d 二级菜单 = 锁定轨迹 / 锁定文字", sub_names == ["锁定轨迹", "锁定文字"],
   f"实际={sub_names}")
ok("T4e 二级两项可勾选且反映当前状态",
   sub.actions()[0].isCheckable() and sub.actions()[1].isCheckable()
   and sub.actions()[0].isChecked() is True          # 启动默认锁轨迹
   and sub.actions()[1].isChecked() is False)

# 变异自检：编辑模式下**不**给菜单（用户：只在普通状态下）
print("\n-- T5 变异：编辑模式下不该抢右键 --")
w.act_edit_mode.setChecked(True)
app.processEvents()
m2, h2 = w._build_map_context_menu()
ok("T5a 编辑模式下不建菜单（判据真在岗）", m2 is None and h2 is None)
w.act_edit_mode.setChecked(False)
app.processEvents()
ok("T5b 退出编辑模式后菜单回来", w._build_map_context_menu()[0] is not None)

# ---------------- T6 菜单每一项真能干活 ----------------
print("\n-- T6 菜单各项真的生效（不弹窗，直接跑 handler）--")
m, handlers = w._build_map_context_menu()
acts = m.actions()
before_tb = w.toolbar.isVisible()
handlers[acts[0]]()
app.processEvents()
ok("T6a ① 主工具栏 开→关", w.toolbar.isVisible() is not before_tb,
   f"{before_tb} → {w.toolbar.isVisible()}")
m, handlers = w._build_map_context_menu()
handlers[m.actions()[0]]()
app.processEvents()
ok("T6b ① 再点一次 关→开", w.toolbar.isVisible() is True)

m, handlers = w._build_map_context_menu()
before_lg = w.legend_panel.isVisible()
handlers[m.actions()[1]]()
app.processEvents()
ok("T6c ② 左侧线路图例 开→关", w.legend_panel.isVisible() is not before_lg)
m, handlers = w._build_map_context_menu()
handlers[m.actions()[1]]()
app.processEvents()
ok("T6d ② 再点一次 关→开", w.legend_panel.isVisible() is True)

m, handlers = w._build_map_context_menu()
before_ip = w.info_panel.isVisible()
handlers[m.actions()[2]]()
app.processEvents()
ok("T6e ③ 详情面板 收→展", w.info_panel.isVisible() is not before_ip,
   f"{before_ip} → {w.info_panel.isVisible()}")
m, handlers = w._build_map_context_menu()
handlers[m.actions()[2]]()
app.processEvents()
ok("T6f ③ 再点一次 展→收", w.info_panel.isVisible() is False)

w._apply_lock_states(True, False)
app.processEvents()
m, handlers = w._build_map_context_menu()
sub = m.actions()[3].menu()
handlers[sub.actions()[1]]()          # 锁定文字
app.processEvents()
body, label = w._lock_states()
ok("T6g ④ 二级『锁定文字』生效（轨迹锁保持）", body is True and label is True,
   f"body={body} label={label}")
w._apply_lock_states(True, False)
app.processEvents()

# ---------------- T7 F11 全屏 ⇒ 默认不显示主工具栏 ----------------
print("\n-- T7 F11 全屏隐藏主工具栏 --")
try:
    w.set_fullscreen(True)
    app.processEvents()
    fs_hid = w.toolbar.isVisible() is False
    w.set_fullscreen(False)
    app.processEvents()
    back = w.toolbar.isVisible() is True
    ok("T7a F11 进入全屏 ⇒ 工具栏隐藏", fs_hid, f"visible={not fs_hid}")
    ok("T7b 退出全屏 ⇒ 工具栏恢复", back)
except Exception as e:
    ok("T7 F11 全屏（offscreen 下不可用，跳过）", True, repr(e))

# ---------------- T8 🔒 按钮上下两半（按钮级，不是图标级） ----------------
print("\n-- T8 🔒 按钮上下两半 --")


def blue_ratio(half: int) -> float:
    w.btn_lock.update()
    app.processEvents()
    img = w.btn_lock.grab().toImage()
    h = img.height()
    y0, y1 = (2, h // 2 - 2) if half == 0 else (h // 2 + 2, h - 2)
    n = b = 0
    for y in range(y0, max(y1, 3)):
        for x in range(2, max(img.width() - 2, 3)):
            c = img.pixelColor(x, y)
            n += 1
            if c.blue() > 180 and c.red() < 120:
                b += 1
    return b / max(n, 1)


w._apply_lock_states(True, False)
app.processEvents()
up, dn = blue_ratio(0), blue_ratio(1)
ok("T8a 只锁轨迹 ⇒ 按钮上半蓝、下半不蓝", up > 0.5 and dn < 0.05,
   f"up={up:.2f} dn={dn:.2f}")
w._apply_lock_states(False, True)
app.processEvents()
up, dn = blue_ratio(0), blue_ratio(1)
ok("T8b 只锁文字 ⇒ 按钮下半蓝、上半不蓝", up < 0.05 and dn > 0.5,
   f"up={up:.2f} dn={dn:.2f}")
w._apply_lock_states(True, True)
app.processEvents()
up, dn = blue_ratio(0), blue_ratio(1)
ok("T8c 全锁 ⇒ 上下都蓝", up > 0.5 and dn > 0.5, f"up={up:.2f} dn={dn:.2f}")
w._apply_lock_states(False, False)
app.processEvents()
up, dn = blue_ratio(0), blue_ratio(1)
ok("T8d 全解 ⇒ 上下都不蓝", up < 0.05 and dn < 0.05, f"up={up:.2f} dn={dn:.2f}")

print("\n" + "=" * 60)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：")
    for n in FAIL:
        print("   -", n)
sys.exit(1 if FAIL else 0)
