# -*- coding: utf-8 -*-
"""v2.7.26 探针：⚙️ 弹窗里两个数字框的单位「px」从框内独立到框外右侧。

用户原话：「把单位 px 独立出去，不要显示在输入框」
（截图里框内显示 "500 p)" —— 单位被箭头挤掉半个 x）。

判据：
  ① 两个数字框的 suffix 为空（框内不再有 px）
  ② 两枚单位标签文字都是 "px"，且在各自框的**右侧**、同一行
  ③ 数字框收短（≤ 80）
  ④ 两个框仍同一行（v2.7.24 的并排不能坏）
  ⑤ ★变异自检：把单位塞回 suffix ⇒ ① 失效
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel          # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402

app = QApplication(sys.argv)
from ui.image_settings_dialog import ImageSettingsDialog    # noqa: E402

dlg = ImageSettingsDialog(None, {}, os.path.abspath("data"))
dlg.show()
for _ in range(12):
    app.processEvents()
    QTest.qWait(10)

PASS = 0
FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK]   {name}   {detail}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}   {detail}")


def gx(w):
    r = w.geometry()
    return r.left()


def gt(w):
    return w.geometry().top()


# ---- ① 框内不再有单位 ----
ok("① sp_info_w 后缀为空（框内无 px）", dlg.sp_info_w.suffix() == "",
   f"suffix={dlg.sp_info_w.suffix()!r} text={dlg.sp_info_w.text()!r}")
ok("①b sp_pan_pad 后缀为空（框内无 px）", dlg.sp_pan_pad.suffix() == "",
   f"suffix={dlg.sp_pan_pad.suffix()!r} text={dlg.sp_pan_pad.text()!r}")

# ---- ② 单位标签在框右侧、同一行 ----
u1 = dlg._lb_px_info
u2 = dlg._lb_px_pad
ok("② 两枚单位标签文字都是 px", u1.text() == "px" and u2.text() == "px",
   f"{u1.text()!r} / {u2.text()!r}")
ok("②b 单位标签在宽度框右侧且同一行",
   gx(u1) >= dlg.sp_info_w.geometry().right()
   and abs(u1.geometry().center().y() -
           dlg.sp_info_w.geometry().center().y()) <= 4,
   f"单位左={gx(u1)} 框右={dlg.sp_info_w.geometry().right()} "
   f"中线 {u1.geometry().center().y()} vs {dlg.sp_info_w.geometry().center().y()}")
ok("②c 单位标签在留白框右侧且同一行",
   gx(u2) >= dlg.sp_pan_pad.geometry().right()
   and abs(u2.geometry().center().y() -
           dlg.sp_pan_pad.geometry().center().y()) <= 4,
   f"单位左={gx(u2)} 框右={dlg.sp_pan_pad.geometry().right()} "
   f"中线 {u2.geometry().center().y()} vs {dlg.sp_pan_pad.geometry().center().y()}")

# ---- ③ 框不再拉长：保持"短框"范畴（≤120）----
# ★ v2.7.27：v2.7.26 时这里判的是"≤80"，但用户实测真机**只能显示一位数字**
#   ⇒ 已加宽到 104（见 _probe_v2727）。这里的口径改成"没被拉成整行那么长"，
#   真正的可读性判据交给 v2.7.27 那个"可显示区 ≥ 4 位数字实宽"的探针。
ok("③ 数字框仍是短框（≤120，没被拉成长条）",
   dlg.sp_info_w.width() <= 120 and dlg.sp_pan_pad.width() <= 120,
   f"宽 {dlg.sp_info_w.width()} / {dlg.sp_pan_pad.width()}")

# ---- ④ 两框仍同行（v2.7.24 的并排没被弄坏）----
ok("④ 两框仍同一行", abs(gt(dlg.sp_info_w) - gt(dlg.sp_pan_pad)) <= 2,
   f"top {gt(dlg.sp_info_w)} vs {gt(dlg.sp_pan_pad)}")
ok("④b 留白那组仍在宽度框右侧",
   gx(dlg.sp_pan_pad) > dlg.sp_info_w.geometry().right() + 8,
   f"留白框左={gx(dlg.sp_pan_pad)} 宽度框右={dlg.sp_info_w.geometry().right()}")

# ---- ⑤ ★变异自检：把单位塞回 suffix ⇒ ① 判据必须失效 ----
dlg.sp_info_w.setSuffix(" px")
for _ in range(6):
    app.processEvents()
    QTest.qWait(10)
ok("⑤ ★变异自检：单位塞回框内 ⇒ '后缀为空'判据失效",
   dlg.sp_info_w.suffix() != "",
   f"suffix={dlg.sp_info_w.suffix()!r}")
dlg.sp_info_w.setSuffix("")

print(f"\n探针：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
