# -*- coding: utf-8 -*-
"""v2.7.27 探针：⚙️ 两个数字框要能完整显示 4 位数字。

用户原话：「两个输入框只能显示一位数字，增加输入框长度，至少可以显示 4 位数字」

判据（不拿"看起来够不够"当依据，实量 QSpinBox 内部 lineEdit 的可显示宽度）：
  ① 框内可显示区宽度 ≥ 4 位数字（"0000"）在当前字体下的实宽
  ② 塞进 8888 之后仍放得下（最宽的那种字形）
  ③ 两个框都 ≥ 96px（保底宽度）
  ④ 弹窗没被这两个框撑宽（≤ 460）
  ⑤ ★变异自检：把框宽强行压回 40px ⇒ ① 必须失效（证明判据真在读宽度）
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402
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


def fits4(spin, sample="0000"):
    """框内的 QLineEdit 实际有多宽 vs 这段数字要占多宽。"""
    le = spin.lineEdit()
    need = spin.fontMetrics().horizontalAdvance(sample)
    return le.width(), need


# ---- ① / ② 可显示区放得下 4 位数字 ----
for tag, spin in (("宽度框 sp_info_w", dlg.sp_info_w),
                  ("留白框 sp_pan_pad", dlg.sp_pan_pad)):
    spin.setValue(1000)
    for _ in range(4):
        app.processEvents()
    w4, need4 = fits4(spin, "0000")
    ok(f"① {tag}：可显示区 ≥ 4 位数字实宽", w4 >= need4,
       f"可用={w4} 需要={need4}")
    spin.setValue(8888)
    for _ in range(4):
        app.processEvents()
    w8, need8 = fits4(spin, "8888")
    ok(f"② {tag}：塞 8888 也放得下", w8 >= need8,
       f"可用={w8} 需要={need8}")

# ---- ③ 保底宽度 ----
ok("③ 两个框宽度 ≥ 96",
   dlg.sp_info_w.width() >= 96 and dlg.sp_pan_pad.width() >= 96,
   f"{dlg.sp_info_w.width()} / {dlg.sp_pan_pad.width()}")

# ---- ④ 弹窗没被撑宽 ----
ok("④ 弹窗宽度仍 ≤ 460", dlg.width() <= 460,
   f"{dlg.width()}x{dlg.height()}")

# ---- ⑤ ★变异自检：把框宽压回 40 ⇒ ① 判据必须失效 ----
old_w = dlg.sp_info_w.width()
dlg.sp_info_w.setFixedWidth(40)
for _ in range(6):
    app.processEvents()
    QTest.qWait(10)
_w, _need = fits4(dlg.sp_info_w, "0000")
ok("⑤ ★变异自检：框宽压到 40 ⇒ '放得下 4 位'判据失效", _w < _need,
   f"可用={_w} 需要={_need}（原宽={old_w}）")
dlg.sp_info_w.setFixedWidth(old_w)
for _ in range(4):
    app.processEvents()

print(f"\n探针：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
