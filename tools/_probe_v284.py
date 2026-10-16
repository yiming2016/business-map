# -*- coding: utf-8 -*-
"""v2.6.84 探针：图标标签行改动验证。
T1 _make_tag_row 生成 4 个上/下/左/右小文字钮，选中态与 _tag_poss 一致
T2 点「上」钮 → _tag_poss[idx]=='top' 且选中态迁移
T3 _pick_tag_icon 全链路不抛 TypeError（monkeypatch exec 拦截）
T4 _set_tag_icon 换图标后按钮贴图更新
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["METROEDITOR_NO_ACTIVATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QDialog

app = QApplication(sys.argv)

from ui.edit_dialog import EditDialog, TAG_POS_BUTTONS

fails = []
def chk(name, cond):
    print(("[PASS] " if cond else "[FAIL] ") + name)
    if not cond:
        fails.append(name)

dlg = EditDialog("深圳北站")   # 有 tags 的站
dlg._ensure_tag_state() if hasattr(dlg, "_ensure_tag_state") else None

# 找到 tag 行控件
n = len(dlg._tag_pos_btns)
chk("T0 tag 槽位数>0 (实际 %d)" % n, n > 0)

# T1 每槽 4 个钮、文字对、选中态一致
ok1 = True
for i in range(n):
    pbs = dlg._tag_pos_btns[i]
    if len(pbs) != 4:
        ok1 = False; break
    for pb, (k, lab) in zip(pbs, TAG_POS_BUTTONS):
        if pb.text() != lab:
            ok1 = False
    cur = dlg._tag_poss[i]
    for pb, (k, lab) in zip(pbs, TAG_POS_BUTTONS):
        if pb.isChecked() != (cur == k):
            ok1 = False
chk("T1 四钮文字/选中态与 _tag_poss 一致", ok1)

# T2 点「上」→ pos 变 top
pb_top = dlg._tag_pos_btns[0][0]
pb_top.click()
chk("T2 点上钮 → _tag_poss[0]=='top'", dlg._tag_poss[0] == "top")
checked = [pb.isChecked() for pb in dlg._tag_pos_btns[0]]
chk("T2b 选中态唯一", checked == [True, False, False, False])

# T3 _pick_tag_icon 不抛异常（拦截 exec）
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

# T4 换图标
dlg._set_tag_icon(0, "shopping")
ok4 = dlg._tag_icons[0] == "shopping"
chk("T4 _set_tag_icon 生效", ok4)

print("RESULT:", "ALL PASS" if not fails else "FAIL %d" % len(fails))
sys.exit(0 if not fails else 1)
