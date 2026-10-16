# -*- coding: utf-8 -*-
"""v2.7.6 探针：滚轮档位改成「等差 +0.5、封顶面板 6.00×」。

用户原话：
  「缩放改为每次滚动变化 0.5，最大值设置为 6（现在的缩放体系下 6 的比例就足够大了）」
  已用 AskUserQuestion 确认：**两个数都是缩放面板上显示的 × 数**
  ⇒ 档位 = 1.00 / 1.50 / 2.00 / … / 6.00（共 11 档），
    内部上限 = 6.0 × ZOOM_BASE ≈ 0.69（不再是 8.0）。

判据清单：
  T1 档位表 = 显示 1.00~6.00 等差 0.5，共 11 档
  T2 内部末档 = 6.0 × ZOOM_BASE，且首档 = ZOOM_BASE
  T3 上限**两处一致**：MapView._zoom_max == 末档 == 滑块 zmax
     （不一致 ⇒ 拖到底一个数、滚轮停在另一个数，历史上 MIN_VIEW_SCALE 踩过）
  T4 面板标签显示：末档 ⇒ "6.00×"，首档 ⇒ "1.00×"
  T5 滚轮一格 = 恰好 +0.5（显示值）；从最小档滚到最大档正好 10 格
  T6 狂滚放大 ⇒ 停在末档 6.00×，不越界；狂滚缩小 ⇒ 停在下限（≥ MIN_VIEW_SCALE）
  T7 跳转定位 2.5× 仍在区间内（没被新上限夹掉）
  T8 变异自检（两条）：① 档位退回等比 ×1.25 ⇒ T1 变红；② 上限退回 8.0 ⇒ T3 变红

★ 铁律：探针不许写真数据、不落盘。这里全程只动 **MainWindow 内存里的缩放状态**，
  不切站、不关窗（那两条路会 flush/落盘）。
"""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import QPoint, QPointF, Qt      # noqa: E402
from PySide6.QtGui import QWheelEvent               # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtTest import QTest                    # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow               # noqa: E402
import ui.map_view as MV                            # noqa: E402

PASS = []


def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)


def pump(n=6):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.show()
pump(20)
mv = win.map_view
sp = mv.scale_panel
BASE = MV.ZOOM_BASE

print("\n-- T1 档位表（显示值）--")
shown = list(MV.ZOOM_STEP_SHOWN)
print(f"     档位数={len(shown)}  {shown}")
want = [round(1.0 + 0.5 * i, 2) for i in range(11)]
ok("T1a 档位 = 1.00~6.00 等差 0.5", shown == want, f"实际={shown}")
ok("T1b 共 11 档", len(shown) == 11, f"{len(shown)} 档")
ok("T1c 相邻档差恒为 0.5",
   all(abs(shown[i + 1] - shown[i] - 0.5) < 1e-9 for i in range(len(shown) - 1)))

print("\n-- T2 内部值 --")
ok("T2a 首档内部 = ZOOM_BASE", abs(MV.ZOOM_STEPS[0] - BASE) < 1e-9,
   f"{MV.ZOOM_STEPS[0]:.4f}")
ok("T2b 末档内部 = 6.0 × ZOOM_BASE", abs(MV.ZOOM_STEPS[-1] - 6.0 * BASE) < 1e-6,
   f"末档={MV.ZOOM_STEPS[-1]:.4f} 期望={6.0 * BASE:.4f}")

print("\n-- T3 上限两处一致 --")
print(f"     MapView._zoom_max={mv._zoom_max:.4f}  末档={MV.ZOOM_STEPS[-1]:.4f}  "
      f"滑块 zmax={sp.zmax:.4f}")
ok("T3a _zoom_max == 档位表末档", abs(mv._zoom_max - MV.ZOOM_STEPS[-1]) < 1e-9)
ok("T3b 滑块 zmax == 档位表末档（滚轮和滑块同一个上限）",
   abs(sp.zmax - MV.ZOOM_STEPS[-1]) < 1e-9)
ok("T3c 上限已不是旧的 8.0", abs(mv._zoom_max - 8.0) > 1.0, f"{mv._zoom_max:.4f}")

print("\n-- T4 面板标签显示 --")


def settle(ms=450):
    """★ 缩放是**动画**（~160ms 收尾），标签画的是**当前动画值**不是目标值。

    第一版只 pump(3)（30ms）就去读标签 ⇒ 读到半路的 4.80× / 1.45×。
    必须等动画真的收敛（实测一格 ~50ms，全流程 450ms 足够）。
    """
    QTest.qWait(ms)
    pump(10)


sp.sld_zoom.setValue(sp.sld_zoom.maximum())
settle()
lab_hi = sp.lab_zoom.text()
sp.sld_zoom.setValue(0)
settle()
lab_lo = sp.lab_zoom.text()
print(f"     最右={lab_hi}  最左={lab_lo}")
ok("T4a 拖到最右显示 6.00×", lab_hi.strip() == "6.00×", lab_hi)
ok("T4b 拖到最左显示 1.00×", lab_lo.strip() == "1.00×", lab_lo)


def wheel(delta, times=1):
    c = mv.viewport().rect().center()
    for _ in range(times):
        ev = QWheelEvent(QPointF(c), mv.viewport().mapToGlobal(QPoint(c)),
                         QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                         Qt.NoModifier, Qt.ScrollUpdate, False)
        mv.wheelEvent(ev)


print("\n-- T5 一格 = +0.5 --")
mv._scale = MV.ZOOM_STEPS[0]
mv._zoom_target = mv._scale
mv._wheel_acc = 0.0
t0 = mv._zoom_target
wheel(120)
t1 = mv._zoom_target
ok("T5a 滚一格：显示值 +0.5", abs(t1 / BASE - (t0 / BASE + 0.5)) < 1e-6,
   f"{t0 / BASE:.2f}× → {t1 / BASE:.2f}×")
ok("T5b 目标正好落在档位表上", any(abs(t1 - s) < 1e-9 for s in MV.ZOOM_STEPS))
# 从最小档一路滚到最大档：正好 10 格
mv._scale = MV.ZOOM_STEPS[0]
mv._zoom_target = mv._scale
mv._wheel_acc = 0.0
for i in range(10):
    wheel(120)
    pump(1)
ok("T5c 最小档起滚 10 格 = 正好到最大档 6.00×",
   abs(mv._zoom_target - MV.ZOOM_STEPS[-1]) < 1e-9,
   f"落点显示={mv._zoom_target / BASE:.2f}×")

print("\n-- T6 狂滚不越界 --")
# ★ 同理：每格之间要给动画留时间（pump(1)=10ms 会导致 `_scale` 一直追不上
#   `_zoom_target`，最后读到的数是半路的，判据就假红了）。
for _ in range(15):
    wheel(120)
    pump(6)
settle()
ok("T6a 狂滚放大 15 格：停在末档，不越界",
   abs(mv._scale - mv._zoom_max) < 0.02 or mv._scale <= mv._zoom_max + 1e-6,
   f"scale={mv._scale:.4f} 上限={mv._zoom_max:.4f}")
ok("T6b 显示值不超过 6.00×", mv._scale / BASE <= 6.0 + 0.05,
   f"{mv._scale / BASE:.2f}×")
for _ in range(15):
    wheel(-120)
    pump(6)
settle()
lo = mv._min_scale_for_viewport()
ok("T6c 狂滚缩小：停在下限附近，不跌破", mv._scale >= lo - 1e-6 and mv._scale <= lo + 0.02,
   f"scale={mv._scale:.4f} 下限={lo:.4f}")
ok("T6d 最小档显示值 ≥ 1.00×", mv._scale / BASE >= 1.0 - 0.02,
   f"{mv._scale / BASE:.2f}×")

print("\n-- T7 跳转定位 2.5× 仍在区间内 --")
mv.zoom_to_station("会展中心")
pump(6)
ok("T7a 跳转后显示值 = 2.5×（没被新上限夹掉）",
   abs(mv._scale / BASE - 2.5) < 0.02, f"{mv._scale / BASE:.3f}×")
ok("T7b 2.5× 确实 ≤ 新上限 6.00×", mv._scale <= mv._zoom_max + 1e-9)

print("\n-- T8 变异自检（两条）--")
# ① 档位退回等比 ×1.25 ⇒ T1 必须变红
_bak_steps = MV.ZOOM_STEPS
_bak_shown = MV.ZOOM_STEP_SHOWN
MV.ZOOM_STEP_SHOWN = tuple(round(1.25 ** i, 2) for i in range(20))
MV.ZOOM_STEPS = tuple(s * BASE for s in MV.ZOOM_STEP_SHOWN)
mut1 = (list(MV.ZOOM_STEP_SHOWN) == want)
MV.ZOOM_STEPS, MV.ZOOM_STEP_SHOWN = _bak_steps, _bak_shown
ok("T8a 变异①：档位退回等比 ⇒ T1 判据变红（判据真在岗）", mut1 is False)

# ② 上限退回 8.0 ⇒ T3 必须变红
_bak_max = mv._zoom_max
mv._zoom_max = 8.0
mut2 = abs(mv._zoom_max - MV.ZOOM_STEPS[-1]) < 1e-9
mv._zoom_max = _bak_max
ok("T8b 变异②：上限退回 8.0 ⇒ T3 判据变红（判据真在岗）", mut2 is False)

n_ok = sum(PASS)
print(f"\n==== v2.7.6 TOTAL {n_ok}/{len(PASS)} 失败 {len(PASS) - n_ok} ====")
# ★ 故意**不** win.close()：MainWindow.close() 里有 dm.save()，会真落盘。
#   这份探针一个字节的数据都没改过，没必要去碰磁盘。
sys.exit(0 if n_ok == len(PASS) else 1)
