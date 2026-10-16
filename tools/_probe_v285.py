# -*- coding: utf-8 -*-
"""v2.6.85 探针：图标标签行改动验证。
T1 方向框=每槽 1 个按钮，文字=当前方向字（默认左）
T2 方向框点击 → _show_tag_pos_menu 全链路不抛异常
T3 _pick_tag_icon 全链路不抛 TypeError（monkeypatch exec 拦截）
T4 _set_tag_pos 改方向后框字同步
T5 选择页行结构=4 行（3/4/4/4）
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QDialog, QMenu

app = QApplication(sys.argv)

from ui.edit_dialog import EditDialog, TAG_POS_CHARS, ICON_CATALOG

fails = []
def chk(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        fails.append(name)

dlg = EditDialog("深圳北站")
n = len(dlg._tag_pos_btns)
chk("T0 tag 槽位数>0 (实际 %d)" % n, n > 0)

# T1 每槽 1 个方向框，字与 _tag_poss 一致
ok1 = all(
    isinstance(dlg._tag_pos_btns[i], object)
    and dlg._tag_pos_btns[i].text() == TAG_POS_CHARS.get(dlg._tag_poss[i], "左")
    for i in range(n))
chk("T1 方向框字=当前方向", ok1)

# T2 点方向框 → 弹菜单链路（替换模块内 QMenu 为桩类，防真实 exec 挂死）
import types
import ui.edit_dialog as ED
RECORD = {}
class FakeSignal:
    def connect(self, *a):
        pass
class FakeAct:
    def __init__(self, t):
        self._t = t
        self.triggered = FakeSignal()
    def text(self):
        return self._t
    def setCheckable(self, *a):
        pass
    def setChecked(self, *a):
        pass
class FakeMenu:
    def __init__(self, parent=None):
        self.acts = []
    def addAction(self, t):
        a = FakeAct(t)
        self.acts.append(a)
        return a
    def exec(self, *a, **k):
        RECORD["acts"] = [a2.text() for a2 in self.acts]
        return 0
orig_qmenu = ED.QMenu
ED.QMenu = FakeMenu
try:
    dlg._tag_pos_btns[0].click()
    ok2 = True
except Exception as e:
    ok2 = False
    print("   exception:", e)
ED.QMenu = orig_qmenu
chk("T2 方向框点击无异常", ok2)
chk("T2b 菜单4项 上/下/左/右", RECORD.get("acts") == ["上", "下", "左", "右"])

# T3 _pick_tag_icon 不抛异常
orig_exec = QDialog.exec
QDialog.exec = lambda self, *a, **k: 0
try:
    dlg._pick_tag_icon(0)
    ok3 = True
except Exception as e:
    ok3 = False
    print("   exception:", e)
QDialog.exec = orig_exec
chk("T3 _pick_tag_icon 无 TypeError", ok3)

# T4 _set_tag_pos 后框字同步
dlg._set_tag_pos(0, "top")
chk("T4 设 top 后框字=上", dlg._tag_pos_btns[0].text() == "上")

# T5 选择页行结构 3/4/4/4
rows_ok = (len(ICON_CATALOG) == 15
           and len(ICON_CATALOG[0:3]) == 3 and len(ICON_CATALOG[3:7]) == 4
           and len(ICON_CATALOG[7:11]) == 4 and len(ICON_CATALOG[11:15]) == 4)
chk("T5 目录 3/4/4/4 行结构", rows_ok)

# T6 组内实测间距（图标→框 8，框→文字 10）
dlg.resize(900, 700)
dlg.show()
app.processEvents()
b0 = dlg._tag_btns[0]
p0 = dlg._tag_pos_btns[0]
e0 = dlg._tag_edits[0]
gap1 = p0.x() - (b0.x() + b0.width())
gap2 = e0.x() - (p0.x() + p0.width())
print("   gap1=%s gap2=%s" % (gap1, gap2))
chk("T6 间距 8/10px", abs(gap1 - 8) <= 1 and abs(gap2 - 10) <= 1)
dlg.hide()

print("RESULT:", "ALL PASS" if not fails else "FAIL %d" % len(fails))
sys.exit(0 if not fails else 1)
