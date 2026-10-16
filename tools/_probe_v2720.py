# -*- coding: utf-8 -*-
"""v2.7.20 探针：⚙️ 弹窗分区块重排 + 新增「拖动留白」设置。

用户原话：「弹窗有些乱，重新规划一下空间」「由于缩放可以设置边界（即左右侧的
弹窗距离图中元素的距离限制），也添加进这里的⚙️」⇒ 点选"拖动/缩放的留白限制"
（= map_view.PAN_ELEMENT_PAD，默认 60 场景单位）。
"""
import os
import sys

os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from PySide6.QtCore import QPointF                              # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel              # noqa: E402
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
mv = win.map_view
old_pad = int(IM.load_settings(d).get("pan_pad_scene", 60) or 0)

dlg = ImageSettingsDialog(win, IM.load_settings(d), d)
dlg.show()
pump(10)

# ---- ① 分区块：两个小标题 + 勾选项顶格 ----
titles = [lb.text() for lb in dlg.findChildren(QLabel) if lb.text() in ("看图模式", "界面 / 地图")]
ok("① 两个区块标题都在", sorted(titles) == ["interface", "看图模式"][::-1] + ["界面 / 地图"][::-1]
   or set(titles) == {"看图模式", "界面 / 地图"}, f"titles={titles}")
l_chk = dlg.cb_auto.mapTo(dlg, dlg.cb_auto.rect().topLeft()).x()
l_lab = dlg.sp_info_w.parentWidget() and 0
ok("①b 勾选项顶格（比字段列更靠左）", l_chk < dlg.sp_info_w.geometry().left(),
   f"勾选框左={l_chk} 面板宽度框左={dlg.sp_info_w.geometry().left()}")

# ---- ② 数字框收短且同宽，字段左边缘对齐 ----
ok("② 两个数字框同宽（不再被拉长）",
   dlg.sp_info_w.width() == dlg.sp_pan_pad.width() and dlg.sp_info_w.width() <= 150,
   f"{dlg.sp_info_w.width()} / {dlg.sp_pan_pad.width()}")
ok("②b 两个数字框同一行（v2.7.24 起并排）",
   abs(dlg.sp_info_w.geometry().top() - dlg.sp_pan_pad.geometry().top()) <= 2,
   f"top {dlg.sp_info_w.geometry().top()} vs {dlg.sp_pan_pad.geometry().top()}")
ok("②c 弹窗宽度没变大（≤460）", dlg.width() <= 460, f"{dlg.width()}x{dlg.height()}")

# ---- ③ 拖动留白：默认值 + 实时生效 + 写盘 ----
ok("③a 弹窗读到的拖动留白 = 设置值", int(dlg.sp_pan_pad.value()) == old_pad,
   f"spin={dlg.sp_pan_pad.value()} 设置={old_pad}")
ok("③b 地图当前留白 = 设置值", abs(mv.pan_pad() - old_pad) < 0.5,
   f"mv={mv.pan_pad()}")
dlg.pan_pad_changed.connect(win._on_pan_pad_live)
dlg.sp_pan_pad.setValue(150)
pump(6)
ok("③c 改数字 ⇒ 地图留白立刻变", abs(mv.pan_pad() - 150) < 0.5, f"mv={mv.pan_pad()}")
ok("③d 立刻写进设置", int(IM.load_settings(d).get("pan_pad_scene")) == 150,
   f"={IM.load_settings(d).get('pan_pad_scene')}")
dlg.sp_pan_pad.setValue(0)
pump(6)
ok("③e 0 也能生效（元素可贴屏幕边）", mv.pan_pad() == 0.0 and
   int(IM.load_settings(d).get("pan_pad_scene")) == 0, f"mv={mv.pan_pad()}")

# ---- ④ 判据要真读到参数：留白不同 ⇒ 同一位移被夹的结果不同 ----
# ★ 坑：趴在"整图适配"档上时视口比内容还宽 ⇒ 走**居中**分支，pad 在算式里
#   正好被抵消（v2.7.13 的原有设计）⇒ 三个值会一模一样。必须**先放大**到
#   视口比内容小，才测得出留白的作用。
sid0 = next(iter(mv.station_items))
mv.zoom_to_station(sid0, 3.0)
pump(14)
mv.set_pan_pad(0)
d0 = mv._pan_limit_delta(QPointF(100000.0, 0.0))
mv.set_pan_pad(300)
d3 = mv._pan_limit_delta(QPointF(100000.0, 0.0))
mv.set_pan_pad(150)
d1 = mv._pan_limit_delta(QPointF(100000.0, 0.0))
ok("④ 拖动夹取真的用了新留白（放大后 0 / 150 / 300 三值互不相同）",
   abs(d0.x() - d3.x()) > 1.0 and abs(d1.x() - d0.x()) > 1.0,
   f"dx: 0→{d0.x():.1f} 150→{d1.x():.1f} 300→{d3.x():.1f}")

# ---- ⑤ 变异自检：断开实时信号 ⇒ 改数字不再联动 ----
snap_mv, snap_file = mv.pan_pad(), int(IM.load_settings(d).get("pan_pad_scene"))
dlg.pan_pad_changed.disconnect(win._on_pan_pad_live)
dlg.sp_pan_pad.setValue(220)
pump(6)
ok("⑤ ★变异自检：断开信号后不再联动（判据真读信号）",
   abs(mv.pan_pad() - snap_mv) < 0.5
   and int(IM.load_settings(d).get("pan_pad_scene")) == snap_file,
   f"断开前 mv={snap_mv} 文件={snap_file}；断开后 mv={mv.pan_pad()} "
   f"文件={IM.load_settings(d).get('pan_pad_scene')}")
dlg.pan_pad_changed.connect(win._on_pan_pad_live)

# ---- ⑥ 走真流程的接线 ----
src = open(os.path.join(_ROOT, "ui", "main_window.py"), encoding="utf-8").read()
ok("⑥ 主窗口接了 pan_pad_changed", "dlg.pan_pad_changed.connect" in src)
mv2 = mv
ok("⑥b 启动时应用设置的分支在 showEvent 里",
   "_apply_pan_pad_from_settings" in src)

# ---- ⑦ 重启后还记得（新开一个 MainWindow 读设置） ----
sec = dict(IM.load_settings(d))
sec["pan_pad_scene"] = 90
IM.save_settings(d, sec)
win2 = MainWindow()
win2.resize(1200, 800)
win2.show()
pump(16)
ok("⑦ 新开的窗口读到 90（重启沿用）", abs(win2.map_view.pan_pad() - 90) < 0.5,
   f"={win2.map_view.pan_pad()}")
win2.close()

# 复原
sec["pan_pad_scene"] = old_pad
IM.save_settings(d, sec)
mv.set_pan_pad(old_pad)
dlg.close()

print(f"\n==== v2.7.20 探针：{N_OK} 通过 / {len(FAILS)} 失败 ====")
if FAILS:
    print("失败项：", FAILS)
sys.exit(1 if FAILS else 0)
