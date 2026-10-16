# -*- coding: utf-8 -*-
"""v2.7.19 探针：⚙️ 弹窗改版。

用户原话：「删除按钮 Cancel」「右侧面板宽度和图片保存到和右侧的数据没有对齐」
          「右侧面板宽度的数值设置为实时改动」「按钮'立即重新生成'移动到
           这些项的左侧，修改按钮形状保证弹出不会因此扩大，刚好塞下」
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton   # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                           # noqa: E402
from ui import image_mode as IM                                 # noqa: E402
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


def pump(n=10):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(20)
d = win._data_dir()
old_w = int(IM.load_settings(d).get("info_panel_w", 520) or 520)

dlg = ImageSettingsDialog(win, IM.load_settings(d), d)
dlg.show()
pump(10)

# ---- ① 底部按钮：只剩「确定」，没有 Cancel ----
btns = [b for b in dlg.findChildren(QPushButton) if b.text() in ("确定", "取消", "OK", "Cancel")]
texts = sorted(b.text() for b in btns)
ok("① 底部只有「确定」", texts == ["确定"], f"按钮={texts}")
ok("①b 源码里不再有 QDialogButtonBox",
   "QDialogButtonBox" not in open(os.path.join(_ROOT, "ui", "image_settings_dialog.py"),
                                 encoding="utf-8").read())

# ---- ② 横向对齐：字段同宽 + 标签顶格左对齐（v2.7.23/24 定案）----
ok("② 两个数字框同宽", dlg.sp_info_w.width() == dlg.sp_pan_pad.width(),
   f"{dlg.sp_info_w.width()} vs {dlg.sp_pan_pad.width()}")
# ★ v2.7.23：用户「全部都要左对齐」⇒ 标签一律顶格，与勾选项同左边缘
#   ★ v2.7.24：「拖动余量」（v2.7.29 前叫「拖动留白」）被挪到第一行右侧了，它不再顶格，排除在外
_labs = [w for w in dlg.findChildren(QLabel)
         if w.text().endswith("：") and w.text() != "拖动余量："]
ok("②a 顶格标签左对齐（右侧面板宽度 / 图片存到）", bool(_labs) and all(
    abs(w.mapTo(dlg, w.rect().topLeft()).x() - dlg.cb_auto.mapTo(dlg, dlg.cb_auto.rect().topLeft()).x()) <= 4
    for w in _labs),
   " / ".join(f"{w.text()}={w.mapTo(dlg, w.rect().topLeft()).x()}" for w in _labs))
# ★ v2.7.20 起：数字框收成短框（不再拉长对齐右边界），勾选项另起一轮顶格
r1 = dlg.sp_info_w.width()
ok("②b 数字框是短框（≤150，不拉长）", r1 <= 150, f"宽={r1}")

# ---- ③ 「立即生成」按钮在"每隔"行最右，且不铺满整行 ----
# ★ v2.7.21：用户改口 —— 按钮从**最左**挪到**本行最右**（"每隔 N 分钟 自动出图"之后）
bn = dlg._btn_now
ok("③ 立即生成按钮在「每隔」行右侧（不再在左）",
   bn.geometry().left() > dlg.cb_timer.geometry().right() + 2,
   f"按钮左={bn.geometry().left()} 每隔行右={dlg.cb_timer.geometry().right()}")
ok("③b 按钮不再铺满整行（宽度 < 弹窗一半）", bn.width() < dlg.width() * 0.5,
   f"按钮宽={bn.width()} 弹窗宽={dlg.width()}")

# ---- ④ 弹窗没变大（旧的硬编码是 460 宽） ----
ok("④ 弹窗宽度没有变大（≤460）", dlg.width() <= 460,
   f"{dlg.width()}x{dlg.height()}")
ok("④b 弹窗比原来更矮（<340）", dlg.height() < 340, f"高={dlg.height()}")

# ---- ⑤ 面板宽度实时生效 + 立刻写盘 ----
# ★ v2.7.28：超过"本机上限"（屏宽×55% 与 780 取小）的数字会被 _info_w_clamp 夹下来
#   ⇒ 期望值要按 cap 算，再挑一个**上限以内**的值来验证"立刻生效 + 立刻写盘"。
_cap = win._overlay_width_cap()
_target = min(640, _cap)
dlg.info_w_changed.connect(win._on_info_w_live)
dlg.sp_info_w.setValue(_target)
pump(6)
ok("⑤a 改数字 ⇒ 面板宽度立刻变", win._info_w == _target,
   f"={win._info_w} 期望={_target}")
ok("⑤b 立刻写进设置", int(IM.load_settings(d).get("info_panel_w")) == _target,
   f"={IM.load_settings(d).get('info_panel_w')} 期望={_target}")
_t2 = min(430, _cap)
dlg.sp_info_w.setValue(_t2)
pump(6)
ok("⑤c 再改 ⇒ 跟着变 + 再写盘",
   win._info_w == _t2 and int(IM.load_settings(d).get("info_panel_w")) == _t2,
   f"内存={win._info_w} 文件={IM.load_settings(d).get('info_panel_w')} 期望={_t2}")
# 立刻生效的判据要能抓病：把信号断开 ⇒ 只改数字不动面板
dlg.info_w_changed.disconnect(win._on_info_w_live)
dlg.sp_info_w.setValue(700)
pump(6)
ok("⑤d ★变异自检：断开实时信号后不再联动（判据真读信号）",
   win._info_w == 430 and int(IM.load_settings(d).get("info_panel_w")) == 430,
   f"内存={win._info_w} 文件={IM.load_settings(d).get('info_panel_w')}")
dlg.info_w_changed.connect(win._on_info_w_live)

# ---- ⑥ 走真流程：_open_image_settings 里确实接了实时信号 ----
src = open(os.path.join(_ROOT, "ui", "main_window.py"), encoding="utf-8").read()
ok("⑥ 主窗口已把 info_w_changed 接上", "dlg.info_w_changed.connect" in src)

# 复原设置
sec = dict(IM.load_settings(d))
sec["info_panel_w"] = old_w
IM.save_settings(d, sec)
win._info_w = old_w
win._layout_overlays()
dlg.close()

print(f"\n==== v2.7.19 探针：{N_OK} 通过 / {len(FAILS)} 失败 ====")
if FAILS:
    print("失败项：", FAILS)
sys.exit(1 if FAILS else 0)
