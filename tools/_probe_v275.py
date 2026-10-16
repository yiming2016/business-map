# -*- coding: utf-8 -*-
"""v2.7.5 探针：出入口改版（标题删除 + 编号按钮 + 详细信息输入框）。

用户原话：
  「删除文字"出入口信息"，出入口新的的这些A、B、C作为按钮，点击后可以输入进行编辑，
    详细信息也应该为输入框。」
  （已用 AskUserQuestion 确认：「每行 = [A按钮] + [输入框]」、
    「详细信息 = 每个出口后面那段文字」）

判据清单：
  T1 「出入口信息」这五个字**在右侧面板和双击弹窗里都不再出现**
     （★ 变异自检：人为塞一个 QLabel 进去 ⇒ 判据必须变红）
  T2 编号是**按钮**：初始显示按钮页；点一下切成输入框页并聚焦；回车/失焦收回按钮；
     Esc 放弃本次改动
  T3 详细信息是**可编辑输入框**（不是只读文本）
  T4 「＋ 添加出入口」回来了（只读态才不建）
  T5 保存链路**确实收集** exits（面板 + 弹窗两处）
  T6 数据零风险：只改**一行**，其它行原样吐回（`text()` 逐行比对）

★ 铁律：探针不许写真数据。这里只读 `_collect()` / `text()` 的返回值，
  **不落盘**；改过的编辑框一律改回去，且全程不切站、不关窗（那两条路会 flush）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import Qt, QTimer          # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit  # noqa: E402
from PySide6.QtTest import QTest               # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow          # noqa: E402
from ui.exits_editor import ExitsEditor, ExitTagChip  # noqa: E402
from ui.edit_dialog import EditDialog          # noqa: E402
from core.schema import HIDDEN_UI_FIELDS, READONLY_UI_FIELDS  # noqa: E402

PASS = []


def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)


def pump(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


def labels_of(w):
    return [x.text() for x in w.findChildren(QLabel)]


def has_title(w, txt="出入口信息"):
    return any(txt in t for t in labels_of(w))


# ================================================================
w = MainWindow()
w.resize(1480, 900)
w.show()
pump(10)
if w.info_panel.isHidden():
    w.btn_info_toggle.click()
    pump()
w._on_station_clicked("世界之窗")
pump(14)

ip = w.info_panel

# ---------------- T1 标题文字已删 ----------------
print("\n== T1 「出入口信息」五个字不再出现 ==")
ok("T1a 右侧面板里搜不到「出入口信息」", not has_title(ip),
   str([t for t in labels_of(ip) if "出入口" in t]))

dlg = EditDialog("会展中心")
app.processEvents()
pump(6)
ok("T1b 双击弹窗里也搜不到「出入口信息」", not has_title(dlg),
   str([t for t in labels_of(dlg) if "出入口" in t]))

# ★ 变异自检：塞一个真 QLabel 进去，判据必须立刻变红
_mut = QLabel("出入口信息", ip)
_mut.show()
pump(4)
ok("T1c 变异（人为塞回标题）⇒ 判据必须变红", has_title(ip))
_mut.setParent(None)
_mut.deleteLater()
pump(4)
ok("T1d 撤掉变异后又变绿", not has_title(ip))

# ---------------- T2 编号 = 按钮 ----------------
print("\n== T2 编号是按钮，点一下才能改 ==")
ex = ip._widgets.get("exits")
ok("T2a 面板里出入口控件回来了", isinstance(ex, ExitsEditor))
ok("T2b 它有出口行", ex is not None and len(ex.rows) >= 2, f"rows={len(ex.rows) if ex else 0}")

chip = ex.rows[0][0]
ok("T2c 编号控件是 ExitTagChip（按钮），不是普通输入框",
   isinstance(chip, ExitTagChip), type(chip).__name__)
ok("T2d 初始停在「按钮页」", chip.currentIndex() == 0, f"idx={chip.currentIndex()}")
ok("T2e 按钮上就是编号原文",
   chip.btn.text() == chip.text().strip(), f"btn={chip.btn.text()!r} text={chip.text()!r}")
ok("T2f 编辑页的输入框此刻不可见", not chip.ed.isVisible())

_orig = chip.text()
# ★ offscreen 下窗口不是"活动窗口"，`hasFocus()` / `focusWidget()` 恒为空 ——
#   不能拿它们当判据（会假失败）。改成**监听 begin_edit 有没有主动要焦点**：
#   真机上"点了按钮就能直接打字"靠的正是这一句 setFocus。
_focus_reqs = []
_orig_setfocus = chip.ed.setFocus


def _spy_setfocus(*a, **k):
    _focus_reqs.append(1)
    try:
        _orig_setfocus(*a, **k)
    except Exception:
        pass


chip.ed.setFocus = _spy_setfocus
chip.btn.click()
pump(4)
ok("T2g 点按钮 ⇒ 切到输入框页", chip.currentIndex() == 1)
ok("T2h 点按钮后会主动把光标交给输入框（真机=点完能直接打字）",
   len(_focus_reqs) == 1, f"setFocus 调用 {len(_focus_reqs)} 次")

# 改个编号 + 回车 ⇒ 按钮文字更新
# ★ `returnPressed` 在内部的 QLineEdit 上（ExitTagChip 只转发它的行为）
chip.ed.setText(_orig + "Z")
chip.ed.returnPressed.emit()
pump(4)
ok("T2i 回车提交 ⇒ 收回按钮页", chip.currentIndex() == 0)
ok("T2j 按钮文字跟着变", chip.btn.text() == (_orig + "Z"),
   f"btn={chip.btn.text()!r}")

# Esc ⇒ 放弃本次编辑
chip.btn.click()
pump(3)
chip.ed.setText("跑偏了")
QTest.keyClick(chip.ed, Qt.Key_Escape)
pump(4)
ok("T2k Esc 放弃 ⇒ 编号回到上一次的值", chip.text() == (_orig + "Z"),
   f"text={chip.text()!r}")
chip.ed.setText(_orig)
chip.ed.returnPressed.emit()
pump(3)
ok("T2l 还原成原编号", chip.text() == _orig, f"{chip.text()!r} vs {_orig!r}")

# ---------------- T3 详细信息 = 输入框 ----------------
print("\n== T3 详细信息是可编辑输入框 ==")
txt = ex.rows[0][1]
ok("T3a 详细信息控件不是只读", not txt.isReadOnly())
_otxt = txt.toPlainText()
txt.setPlainText(_otxt + "【探针】")
pump(3)
ok("T3b 改完之后 text() 里带上了新内容", "【探针】" in ex.text())
txt.setPlainText(_otxt)          # ★ 立刻改回来，后面不落盘
pump(3)
ok("T3c 改回原值后 text() 复原", "【探针】" not in ex.text())

# ---------------- T4 添加按钮回来 ----------------
print("\n== T4 「＋ 添加出入口」回来了 ==")
ok("T4a 有添加按钮", getattr(ex, "_add_btn", None) is not None)
n0 = len(ex.rows)
ex.add_row()
pump(4)
ok("T4b 点一下多一行", len(ex.rows) == n0 + 1, f"{n0} -> {len(ex.rows)}")
ok("T4c 新行也是按钮形态", isinstance(ex.rows[-1][0], ExitTagChip))
# 空行不写进 text()（原有行为），撤掉它
row_w = ex.rows[-1][0].parentWidget()
ex.rows.pop()
row_w.setParent(None)
row_w.deleteLater()
pump(3)

# ---------------- T5 保存链路确实收集 exits ----------------
print("\n== T5 保存链路收 exits（两处）==")
ok("T5a exits 不在只读集合里了", "exits" not in READONLY_UI_FIELDS,
   str(READONLY_UI_FIELDS))
ok("T5b exits 不在隐藏集合里", "exits" not in HIDDEN_UI_FIELDS,
   str(HIDDEN_UI_FIELDS))
p_payload = ip._collect()
ok("T5c 右侧面板 _collect() 带上了 exits", "exits" in p_payload)
ok("T5d 收上来的内容和控件 text() 一致",
   p_payload.get("exits") == ex.text())
d_payload = dlg._collect()
ok("T5e 编辑弹窗 _collect() 带上了 exits", "exits" in d_payload)
ok("T5f 弹窗侧也不含 facilities", "facilities" not in d_payload)

# ---------------- T6 数据零风险：只改一行不影响别行 ----------------
print("\n== T6 只改一行 ⇒ 其它行原样吐回 ==")
raw = json.load(open(r"C:\software\subway\软件\data\stations.json", encoding="utf-8"))
rec = (raw.get("stations") or {}).get("世界之窗") or {}
src_lines = [ln for ln in str(rec.get("exits") or "").splitlines() if ln.strip()]
out_lines = ex.text().splitlines()
ok("T6a 行数一致（没多也没少）", len(src_lines) == len(out_lines),
   f"{len(src_lines)} vs {len(out_lines)}")
_same = sum(1 for a, b in zip(src_lines, out_lines) if a.strip() == b.strip())
ok("T6b 逐行原文一致（未动过的行一字不改）", _same == len(src_lines),
   f"一致 {_same}/{len(src_lines)}")

# 改第二行 ⇒ 只有第二行变
r1 = ex.rows[1]
_ot = r1[1].toPlainText()
r1[0].ed.setText("XY")
r1[0].ed.returnPressed.emit()
pump(3)
out2 = ex.text().splitlines()
ok("T6c 改过的行重拼成「XY出入口：原内容」",
   out2[1].strip() == "XY出入口：%s" % _ot.strip(), out2[1][:40])
ok("T6d 其它行仍是一字不改",
   all(out2[i].strip() == src_lines[i].strip()
       for i in range(len(src_lines)) if i != 1))
# ★★ 全部还原（探针绝不改数据）
r1[0].ed.setText(ex.rows[1][2])
r1[0].ed.returnPressed.emit()
pump(3)
ok("T6e 还原后逐行又与原文件完全一致",
   all(a.strip() == b.strip() for a, b in zip(src_lines, ex.text().splitlines())))

# ================================================================
n_ok = sum(PASS)
print("\n==== v2.7.5 TOTAL %d/%d 失败 %d ====" % (n_ok, len(PASS), len(PASS) - n_ok))
sys.exit(0 if n_ok == len(PASS) else 1)
