# -*- coding: utf-8 -*-
"""
tools/_chk_map_cursor.py
========================
回归：地图的**自定义光标**（**极简圆点**，v2.6.13 换掉系统手掌）。

用户原话（两轮才定下来）：
    「可以把抓手换成其他风格吗？比如说符合现代主题的一个圆圈或什么类型」
    → 第一版「圆环+圆心」→「我不喜欢这个样子，还有其他选择吗」
    → 8 种对比图 → 用户选 **E 极简圆点** + 「收敛一点」
⇒ 定型：静止**只有一个小实心圆点**（r=3.4，直径 6.8px）；
   拖动圆点**变小**（3.4→2.6）+ 外面**浮出一圈细环**（r=6.6）；
   **站点上保留系统手指手型**。
★ 形状参数顺序 (圆心半径, 外圈细环半径, 环线宽) —— 与「圆环+圆心」那版
  的 (环半径, 环线宽, 圆心半径) **不一样**。★ v2.6.13 第二版就是在这里
  吃过亏：参数换了顺序但断言没改，于是断言拿"圆心"变量去比环线宽、
  拿"环"变量去比圆心半径 —— 数字碰巧还是对的方向，**标签和语义全错**，
  下次再调参数就会得出假结论。改形状必须连这里的断言一起改。

守四件事：
  A 位图**真的画上了东西**（非透明像素在合理区间）——
    ★ 只断言"`setCursor` 被调用过"是没有意义的：画失败时位图全透明，
      光标在屏幕上直接消失，而调用记录照样是成功的。
  B 两个状态**位图不一样**（拖动真的换形状）+ 热点在**正中心**
  C 接进 `MapView` 之后：空白=自绘圆环 / 拖动=自绘 drag / **站点上仍是手指**
  D 变异自检：①形状画成空操作 ⇒ A 必须失败；②热点写回 `QCursor(pm)` 默认值 ⇒ B 失败

★ 测试不许写真数据（`MainWindow.close()` 里有 `dm.save()`）⇒ 数据指到临时副本。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="v2612cur_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import Qt, QPoint                        # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap          # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

import ui.map_cursor as MC                                   # noqa: E402
from ui.main_window import MainWindow                        # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 12) -> None:
    for _ in range(n):
        QApplication.processEvents()


def opaque_n(pm: QPixmap) -> int:
    """非透明像素个数（= "到底有没有画上东西"的硬判据）。"""
    im = pm.toImage()
    return sum(1 for y in range(im.height()) for x in range(im.width())
               if im.pixelColor(x, y).alpha() > 8)


def bytes_of(pm: QPixmap) -> bytes:
    im = pm.toImage()
    return bytes(im.constBits())


def main() -> int:
    app = QApplication(sys.argv)
    total = MC.BOX * MC.DPR * MC.BOX * MC.DPR

    print("\n===== A 位图必须真的画上了东西 =====")
    # ★ 下界 4% 而不是 6%：用户要求"收敛一点"，静止态现在**只有一个小圆点**，
    #   实测只占画布 318/4096 = 7.8%。下界留在 6% 的话，再收敛一点点就会
    #   **假失败**（明明画上了，却判"没画上"）。4% 仍能抓住"画成空操作"（0 px）。
    lo, hi = 0.04 * total, 0.55 * total
    for kind in ("open", "drag"):
        n = opaque_n(MC.pixmap_of(kind))
        check("%s 态位图的非透明像素在合理区间（既不是空、也不是实心块）" % kind,
              lo <= n <= hi, "%d px（画布 %d，允许 %.0f~%.0f）"
              % (n, total, lo, hi))

    print("\n===== B 两个状态不同 + 热点居中 =====")
    pm_o, pm_d = MC.pixmap_of("open"), MC.pixmap_of("drag")
    check("静止态与拖动态的位图**不一样**（拖动真的换形状）",
          bytes_of(pm_o) != bytes_of(pm_d),
          f"静止 {opaque_n(pm_o)} px vs 拖动 {opaque_n(pm_d)} px")
    # ★ 写这条必须**对着参数顺序写**：OPEN/DRAG = (圆心半径, 外圈细环半径, 环线宽)
    check("拖动时**圆点变小**、并**浮出一圈细环**（静止只有一个点）",
          MC.DRAG[0] < MC.OPEN[0]
          and MC.OPEN[1] < 0.1 and MC.DRAG[1] > 0.1,
          f"圆点半径 {MC.OPEN[0]}→{MC.DRAG[0]}，外环半径 {MC.OPEN[1]}→{MC.DRAG[1]}")
    # ★ 上面比的是**参数**，这条比的是**真位图**：环浮出来 ⇒ 覆盖面积必然变大。
    #   参数对了画错了（比如环画在了圆心位置）只有这条能抓到。
    check("拖动态**覆盖面积明显更大**（环真的浮出来了）—— 数真位图，不靠参数猜",
          opaque_n(pm_d) > opaque_n(pm_o) * 1.5,
          f"静止 {opaque_n(pm_o)} px → 拖动 {opaque_n(pm_d)} px")
    for kind in ("open", "drag"):
        c = MC.cursor(kind)
        want = int(MC.BOX * MC.DPR / 2)
        check("%s 态热点在**正中心**（%d,%d）" % (kind, want, want),
              (c.hotSpot().x(), c.hotSpot().y()) == (want, want),
              f"实际 {c.hotSpot().x()},{c.hotSpot().y()}")
    check("位图带 devicePixelRatio=2（高 DPI 下不发虚）且逻辑尺寸 = %d" % MC.BOX,
          abs(pm_o.devicePixelRatio() - 2.0) < 0.01
          and int(pm_o.width() / pm_o.devicePixelRatio()) == MC.BOX,
          "位图 %dx%d dpr=%.1f"
          % (pm_o.width(), pm_o.height(), pm_o.devicePixelRatio()))

    print("\n===== C 接进 MapView 之后 =====")
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view
    vp = mv.viewport()

    # 空白处（拿一个远离所有站点的视口位置）
    far = QPoint(vp.rect().width() - 6, vp.rect().height() - 6)
    mv._sync_cursor(far, force=True)
    pump(6)
    check("空白处：用的是**自绘位图光标**（不再系统的张开手掌）",
          mv._cursor_kind == "open"
          and vp.cursor().shape() == Qt.BitmapCursor
          and vp.cursor().pixmap().size() == pm_o.size(),
          f"kind={mv._cursor_kind} shape={vp.cursor().shape()}")

    # 站点上
    sid = next(iter(mv.station_items.keys()))
    sit = mv.station_items[sid]
    mv.centerOn(sit.pos())
    pump(10)
    vp_pos = mv.mapFromScene(sit.pos())
    mv._sync_cursor(vp_pos, force=True)
    pump(6)
    check("站点上：仍然是系统的**手指手型**（「可点击」是通用语义，没被换掉）",
          mv._cursor_kind == "point"
          and vp.cursor().shape() == Qt.PointingHandCursor,
          f"kind={mv._cursor_kind} shape={vp.cursor().shape()}")

    # 拖动中
    mv._panning = True
    mv._sync_cursor(vp_pos, force=True)
    pump(6)
    check("拖动中：换成**自绘 drag 位图**（圆点变小 + 浮出细环），不是系统握拳",
          mv._cursor_kind == "drag"
          and vp.cursor().shape() == Qt.BitmapCursor
          and vp.cursor().pixmap().size() == pm_d.size(),
          f"kind={mv._cursor_kind} shape={vp.cursor().shape()}")
    # ★ 这条不是凑数：它证明「要不要换光标」**不能**沿用旧的 `cur.shape() != want`。
    #   （`_sync_cursor` 原来就是这么写的，换成位图光标后会**静默失效** ——
    #    两个状态的 shape() 都是 BitmapCursor，拖动时光标根本不会变。）
    check("两个自绘光标的 `shape()` **完全相同**（都是 BitmapCursor）"
          "⇒ 「要不要换」绝不能靠 `shape()` 比较",
          MC.cursor("open").shape() == Qt.BitmapCursor
          and MC.cursor("drag").shape() == Qt.BitmapCursor
          and bytes_of(MC.pixmap_of("open")) != bytes_of(MC.pixmap_of("drag")),
          "shape 一样但位图不一样")
    mv._panning = False
    mv._sync_cursor(far, force=True)
    pump(6)
    check("松手后回到 open 态", mv._cursor_kind == "open",
          f"kind={mv._cursor_kind}")

    print("\n===== D 变异自检 =====")
    old_paint = MC.paint_shape
    MC.paint_shape = lambda p, shape: None          # 什么都不画
    MC._CACHE.clear()
    n_blank = opaque_n(MC.pixmap_of("open"))
    check("变异（形状画成空操作）后位图**全透明** ⇒ A 判据真在上岗",
          not (lo <= n_blank <= hi), f"变异后 {n_blank} px")
    MC.paint_shape = old_paint
    MC._CACHE.clear()

    # ★ QCursor(pm) 的默认热点在有 dpr 时是错的（实测 dpr=2 时给 (16,16) 而非 (32,32)）
    pm = MC._paint(MC.OPEN)
    from PySide6.QtGui import QCursor
    bad = QCursor(pm)
    want = int(MC.BOX * MC.DPR / 2)
    check("变异（热点用 `QCursor(pm)` 的默认值）后**不在中心** ⇒ B 判据真在上岗",
          (bad.hotSpot().x(), bad.hotSpot().y()) != (want, want),
          "默认热点 (%d,%d)，中心应为 (%d,%d)"
          % (bad.hotSpot().x(), bad.hotSpot().y(), want, want))

    print("\n===== 结果：%d 通过 / %d 失败 =====" % (PASS, FAIL))
    for n in FAILED:
        print("  - " + n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
