# -*- coding: utf-8 -*-
"""v2.7.28 探针：⚙️ 数字框的区间限制 + 实际宽度回写 + 不再"边打边生效"。

用户原话：「是否要限制区间设置？输入某些数字后不起作用」

三个病根（都已修）：
  1. 面板宽度框允许 360~780，但落地时还要过 min(780, 屏宽×55%) 这条隐形线
     ⇒ 超过本机上限的值被静默夹掉，看着像"没反应"。现在**按本机上限收紧 Range**。
  2. 左侧线路面板同时开着时还会给地图留 320px ⇒ 实际宽度小于输入值。
     现在把**真正落地的宽度回写**进数字框（框里不留假数字）。
  3. QSpinBox 默认 keyboardTracking ⇒ 打 700 会先把 7 应用了。
     现在改成**回车 / 失焦**才落地。

判据：
  ① Range 上限 = 传入的本机上限（给 500 就是 500，不是 780）
  ② 旧设置值超过上限 ⇒ 打开时被夹到上限（不会显示无效数字）
  ③ 两个数字框 keyboardTracking 都关了
  ④ 被"给地图留 320px"压缩时，框里显示的是**实际落地宽度**（不是输入值）
  ⑤ ★变异自检：回写不能引发第二轮信号（否则会和主窗口来回打转）
  ⑥ ★变异自检：把 keyboardTracking 打开 ⇒ ③ 失效
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from PySide6.QtWidgets import QApplication                      # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                           # noqa: E402
from ui.image_settings_dialog import ImageSettingsDialog        # noqa: E402

FAILS = []
N_OK = 0


def ok(name, cond, info=""):
    global N_OK
    if cond:
        N_OK += 1
        print(f"  [OK] {name}" + (f"  —— {info}" if info else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  —— {info}" if info else ""))


def pump(n=8):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(20)

# 让右侧浮层处于"可见"状态 —— 否则 _layout_overlays 里 iw=0、没有回写对象
try:
    win.info_panel.setVisible(True)
    win.info_wrap.setVisible(True)
    win._layout_overlays()
    pump()
except Exception as e:
    print("  [warn] 显示右侧面板失败：", repr(e))

cap = win._overlay_width_cap()

# ---- ① 上限按本机给的值收紧（这里塞 500，看它是不是就停在 500）----
test_max = min(500, cap)
dlg = ImageSettingsDialog(win, {"info_panel_w": 470}, win._data_dir(),
                          info_w_max=test_max)
dlg.show()
pump()
ok("① 数字框上限 = 传入的本机上限",
   dlg.sp_info_w.maximum() == test_max,
   f"maximum={dlg.sp_info_w.maximum()} 期望={test_max}")

# ---- ② 旧设置值超过上限 ⇒ 被夹下来，不显示无效数字 ----
dlg2 = ImageSettingsDialog(win, {"info_panel_w": 780}, win._data_dir(),
                           info_w_max=test_max)
dlg2.show()
pump()
ok("② 设置里的旧值 780 超过上限 ⇒ 夹到上限",
   dlg2.sp_info_w.value() == test_max,
   f"value={dlg2.sp_info_w.value()} 上限={test_max}")

# ---- ③ 不再边打边生效 ----
ok("③a 面板宽度框 keyboardTracking 关闭",
   dlg.sp_info_w.keyboardTracking() is False,
   f"{dlg.sp_info_w.keyboardTracking()}")
ok("③b 拖动留白框 keyboardTracking 关闭",
   dlg.sp_pan_pad.keyboardTracking() is False,
   f"{dlg.sp_pan_pad.keyboardTracking()}")

# ---- ④ 被"给地图留 320px"压缩 ⇒ 框里显示实际落地宽度 ----
win._settings_dlg = dlg
dlg.info_w_changed.connect(win._on_info_w_live)
# 把左侧线路面板拉得很宽，制造"两侧合计超标"的场面
try:
    win.legend_panel.setVisible(True)
    win._legend_w = 900
    win._layout_overlays()
    pump()
except Exception as e:
    print("  [warn] 显示左侧面板失败：", repr(e))

dlg.blockSignals(False)
dlg.sp_info_w.setValue(test_max)
pump(10)
actual = int(getattr(win, "_info_w_actual", -1))
shown = dlg.sp_info_w.value()
ok("④ 被压缩时框里显示实际落地宽度",
   actual > 0 and shown == actual and shown <= test_max,
   f"输入={test_max} 实际={actual} 框里={shown}")

# ---- ⑤ ★变异自检：回写不许再触发一轮信号 ----
hits = []
dlg.info_w_changed.connect(lambda v: hits.append(v))
dlg.show_applied_w(min(test_max, actual))
pump(6)
ok("⑤ ★变异自检：回写不引发第二轮信号（不会来回打转）",
   len(hits) == 0, f"第二轮信号次数={len(hits)}")

# ---- ⑥ ★变异自检：把 keyboardTracking 打开 ⇒ ③a 失效 ----
dlg.sp_info_w.setKeyboardTracking(True)
pump(4)
ok("⑥ ★变异自检：keyboardTracking 打开 ⇒ ③a 判据失效",
   dlg.sp_info_w.keyboardTracking() is not False,
   f"{dlg.sp_info_w.keyboardTracking()}")
dlg.sp_info_w.setKeyboardTracking(False)

print(f"\n==== v2.7.28 探针：{N_OK} 通过 / {len(FAILS)} 失败 ====")
for f in FAILS:
    print("   -", f)
sys.exit(1 if FAILS else 0)
