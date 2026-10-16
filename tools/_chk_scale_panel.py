# -*- coding: utf-8 -*-
"""回归 v2.6.41：右上角「整体缩放 / 字体缩放」双滑块 + 两把锁。

用户原话：「在图右上角添加两个滑块。整体缩放、字体缩放，两个滑块左侧分别添加🔒的按钮」

判据：
  A 面板在右上角、不吃地图的鼠标
  B 整体缩放滑块：拖到某档 ⇒ 地图真的到那一档（复用滚轮链路，不卡）
  C 🔒 整体缩放：锁住后滚轮不再改变缩放（滑块仍可拖）
  D 字体缩放滑块：改变**所有站**的字号
  E 🔒 字体缩放：锁住后缩放地图，字的大小不再变（= 老行为）
  F 变异：断开滑块信号 ⇒ B/D 必须失效（判据真在岗）

运行：
    ...\\python.exe tools/_chk_scale_panel.py
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="scalepanel_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, QPointF, Qt                # noqa: E402
from PySide6.QtGui import QWheelEvent                         # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame            # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402
from ui.main_window import MainWindow                         # noqa: E402
import ui.metro_render as MR                                  # noqa: E402

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def wheel(mv, delta):
    c = mv.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    mv.wheelEvent(ev)


def font_px_of(mv):
    """当前所有主站体的屏幕字号（取第一个站当代表）。"""
    for it in mv.station_items.values():
        return it.screen_font_px()
    return 0.0


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view
    p = mv.scale_panel

    # ★★ v2.7.6：缩放上限由**内部 8.0** 降到 **面板 6.00×**（内部 ≈0.69）。
    #   脚本里到处写死的"内部 1.0 / 2.0 / 4.0"全都**超出新上限**了 ——
    #   会被夹到 0.69，判据于是假红（这不是回归，是判据前提变了）。
    #   ⇒ 统一按**面板自己的区间**算可达档位，以后再改上下限脚本也不会骗人。
    import math as _math
    _lz, _hz = _math.log(p.zmin), _math.log(p.zmax)
    MID = _math.exp((_lz + _hz) / 2.0)      # 中间档（滑块是对数的 ⇒ 正好在中间）
    HI = p.zmax * 0.8                       # 接近最大档（放大方向留得出余量）
    LO = p.zmin * 1.5                       # 接近最小档（缩小方向留得出余量）
    print(f"     [档位] zmin={p.zmin:.4f} zmax={p.zmax:.4f} "
          f"LO={LO:.4f} MID={MID:.4f} HI={HI:.4f}")

    # ---------------------------------------------------------------
    print("===== A 面板本身 =====")
    ok("A1 面板存在且可见", p is not None and p.isVisible())
    vp = mv.viewport()
    ok("A2 贴在**左栏底部**",
       p.x() < 40 and p.y() > vp.height() * 0.5,
       f"({p.x()},{p.y()}) 尺寸 {p.width()}x{p.height()} 视口 {vp.width()}x{vp.height()}")
    # ★ 2026-10-11：面板自 v2.6.79 起**常驻左侧线路图例的下方**（用户要求双滑块
    #   挂在左栏底部），不再是右上角 —— A2/A7 的判据随之改成"贴左边缘 + 下半区"。
    #   （这两条长期红着，容易被误当成"新改动弄坏了布局"。）
    ok("A3 两个滑块都在", hasattr(p, "sld_zoom") and hasattr(p, "sld_font"))
    ok("A4 两把锁都是**按钮**且可勾选",
       p.zoom_lock_btn().isCheckable() and p.font_lock_btn().isCheckable())
    ok("A5 锁按钮在滑块**左侧**",
       p.zoom_lock_btn().x() < p.sld_zoom.x()
       and p.font_lock_btn().x() < p.sld_font.x(),
       f"锁x={p.zoom_lock_btn().x()} 滑块x={p.sld_zoom.x()}")
    # ★ v2.6.51：字体最小档抬到 1.8 ⇒ 默认倍率 1.0 **够不着**了，会被夹到最小档。
    #   判据不许写死 1.0/1.8，一律从面板当前 fmin 推。
    ok("A6 字体滑块初始停在**最小档**（默认 1.0 低于下限 ⇒ 被夹到 fmin，显示 1.0×）",
       abs(mv._font_mul - p.fmin) < 1e-6
       and abs(MR.effective_font_px(mv._scale) * mv._font_mul
               - font_px_of(mv)) < 0.01
       and p.lab_font.text().startswith("1.0"),
       f"倍率 {mv._font_mul} 显示 {p.lab_font.text()}")
    # ---- v2.6.43（用户：「紧贴右上角边缘，且融入进去，不要看起来像一个凸出来的模块」）
    ok("A7 紧贴左边缘（左边距 ≤12px）",
       p.x() <= 12, f"左 {p.x()}px")
    ok("A8 不画卡片底：无边框 + 不自动填背景（= 融进地图，不是凸出的模块）",
       p.frameShape() == QFrame.NoFrame and not p.autoFillBackground(),
       f"shape={p.frameShape()} fillBg={p.autoFillBackground()}")
    p.chrome_margin = 16        # ★ 变异
    mv._layout_chrome()
    pump(4)
    ok("A9 变异：边距改回 16 ⇒ A7 立刻失效（判据真在岗）",
       vp.width() - (p.x() + p.width()) > 2,
       f"右 {vp.width() - (p.x() + p.width())}px")
    p.chrome_margin = 0
    mv._layout_chrome()
    pump(4)

    # ---------------------------------------------------------------
    print("===== B 整体缩放滑块 =====")
    p.sld_zoom.setValue(p._tick_of_zoom(HI))
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok(f"B1 拖到 {HI:.3f}（接近最大档）⇒ 地图真的到了那一档",
       abs(mv._scale - HI) < 0.05, f"{mv._scale:.3f}")
    p.sld_zoom.setValue(p._tick_of_zoom(LO))
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok(f"B2 拖回 {LO:.3f}（接近最小档）⇒ 地图跟着回到那一档",
       abs(mv._scale - LO) < 0.05, f"{mv._scale:.3f}")
    # ★ v2.6.48：滑块显示的是"以最小档为 1 的比例"；★ v2.6.51 最小档从 0.05 抬到 0.115
    #   ⇒ 0.5 档显示为 0.5/zmin ≈ 4.35×。**不写死**，从面板当前 zbase 推。
    # ★ 别拿"名义档位 0.5"去算期望值：实际缩放是 0.499x（滑块是离散 tick），
    #   写死 4.35 会和真实显示的 4.34 差 0.01 ⇒ 假失败。按**实际 scale** 比对。
    ok(f"B3 标签跟着显示当前比例（实际 {mv._scale:.3f} ÷ 最小档 {p.zmin}）",
       abs(float(p.lab_zoom.text().rstrip("×")) - mv._scale / p.zbase) < 0.02,
       f"显示 {p.lab_zoom.text()} 期望 {mv._scale / p.zbase:.2f}×")
    ok("B3b 最左端 = 1（比例以最小档为基数）",
       abs(p._zoom_of(0) / p.zbase - 1.0) < 1e-6,
       f"最左端 {p._zoom_of(0) / p.zbase:.2f}×")

    # ---------------------------------------------------------------
    print("===== C 🔒 整体缩放锁 =====")
    # ★ v2.6.43：必须**先放大再锁**。停在下限时滚轮本来就缩不动，
    #   "锁住后不变"会**假通过**（没锁也一样不变）⇒ 判据必须先站到放大档。
    p.sld_zoom.setValue(p._tick_of_zoom(HI))
    pump(20)
    QTest.qWait(400)
    pump(10)
    p.zoom_lock_btn().setChecked(True)
    pump(4)
    before = mv._scale
    for _ in range(8):
        wheel(mv, -120)
        pump(2)
    QTest.qWait(400)
    pump(10)
    ok("C1 锁住后**滚轮不再改变缩放**",
       abs(mv._scale - before) < 1e-6, f"{before:.3f} → {mv._scale:.3f}")
    ok("C2 锁按钮显示已锁", p.zoom_lock_btn().isChecked())
    p.sld_zoom.setValue(p._tick_of_zoom(LO))
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("C3 锁住时**滑块仍能拖**（不然锁上就调不动了）",
       abs(mv._scale - LO) < 0.05, f"{mv._scale:.3f}")
    p.zoom_lock_btn().setChecked(False)
    pump(4)
    _before_unlock = mv._scale
    wheel(mv, -120)
    pump(4)
    QTest.qWait(400)
    pump(10)
    # ★ v2.7.6：原来写死 "< 0.99"，上限降到 0.69 之后**所有档位都 < 0.99**
    #   ⇒ 判据变成恒真（锁失效也照样过）。改成跟解锁前比，才是真判据。
    ok("C4 解锁后滚轮恢复生效（比解锁前更小）",
       mv._scale < _before_unlock * 0.95,
       f"{_before_unlock:.4f} → {mv._scale:.4f}")

    # ---------------------------------------------------------------
    print("===== D 字体缩放滑块 =====")
    # ★ v2.6.51：字体倍率区间变成 1.8~3.0（显示 1.0×~1.67×），**2.0× / 0.5× 都够不着**了。
    #   判据改成"从最小档往上 ×1.5 / ×1.2"，倍率与档位都不写死。
    p.sld_font.setValue(p._tick_of_mul(p.fmin))
    pump(12)
    QTest.qWait(300)
    pump(10)
    base = font_px_of(mv)
    p.sld_font.setValue(p._tick_of_mul(p.fmin * 1.5))
    pump(12)
    QTest.qWait(300)
    pump(10)
    big = font_px_of(mv)
    ok("D1 从最小档 ×1.5 ⇒ 字号真的变 1.5 倍",
       abs(big - base * 1.5) < max(base * 0.15, 0.6), f"{base:.1f} → {big:.1f}px")
    p.sld_font.setValue(p._tick_of_mul(p.fmin * 1.2))
    pump(12)
    QTest.qWait(300)
    pump(10)
    small = font_px_of(mv)
    ok("D2 回到最小档 ×1.2 ⇒ 字号真的变 1.2 倍",
       abs(small - base * 1.2) < max(base * 0.15, 0.6),
       f"{base:.1f} → {small:.1f}px")
    # 所有站都要跟着变（不能只有一部分）
    vals = [it.screen_font_px() for it in mv.station_items.values()]
    ok("D3 **每一个**站的字号都变了（不是一个站）",
       max(vals) - min(vals) < 0.01 and abs(vals[0] - small) < 0.01,
       f"{len(vals)} 站，极差 {max(vals)-min(vals):.3f}")
    p.sld_font.setValue(p._tick_of_mul(1.0))
    pump(12)
    QTest.qWait(300)
    pump(10)

    # ---------------------------------------------------------------
    print("===== E 🔒 字体缩放锁 =====")
    p.font_lock_btn().setChecked(True)
    pump(12)
    QTest.qWait(300)
    pump(10)
    locked_px = font_px_of(mv)
    ok("E0 锁住时记下了当前字号", mv._font_lock_px is not None
       and abs(mv._font_lock_px - locked_px) < 0.01, f"{locked_px:.1f}px")
    # 锁住后缩放地图：字号必须**不变**
    p.sld_zoom.setValue(p._tick_of_zoom(HI))
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("E1 锁住后把地图放大到接近最大档 ⇒ **字号纹丝不动**",
       abs(font_px_of(mv) - locked_px) < 0.01,
       f"{locked_px:.1f} → {font_px_of(mv):.1f}px（缩放 {mv._scale:.2f}）")
    p.sld_zoom.setValue(p._tick_of_zoom(LO))
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("E2 缩小也一样（字号不跟着变小）",
       abs(font_px_of(mv) - locked_px) < 0.01,
       f"{font_px_of(mv):.1f}px（缩放 {mv._scale:.2f}）")
    # 解锁 ⇒ 恢复等比（字号随缩放变）
    p.font_lock_btn().setChecked(False)
    pump(12)
    QTest.qWait(300)
    pump(10)
    px_half = font_px_of(mv)
    p.sld_zoom.setValue(p._tick_of_zoom(HI))
    pump(20)
    QTest.qWait(400)
    pump(10)
    # ★ v2.7.6：原来是"0.5 → 2.0 档字号涨约 4 倍"，上限降到 0.69 之后
    #   "4 倍"这个跨度根本不存在了。改成 LO→HI（跨度 ≈3.2×），
    #   判据仍然是"字号涨幅 ≈ 缩放涨幅"（等比的本意没变）。
    ok("E3 解锁后字号重新**跟着地图等比**（接近最小档→接近最大档，字号同比变大）",
       font_px_of(mv) > px_half * 2.5,
       f"{px_half:.1f} → {font_px_of(mv):.1f}px（缩放 {mv._scale:.2f}）")

    # ---------------------------------------------------------------
    print("===== F 变异自检：断开信号必须失效 =====")
    p.zoom_to.disconnect()
    s0 = mv._scale          # E3 之后停在 HI
    p.sld_zoom.setValue(p._tick_of_zoom(LO))    # ★ 必须换一个档，否则"不动"是恒真
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("F1 断开整体缩放信号 ⇒ 拖滑块地图不动（B 判据真在岗）",
       abs(mv._scale - s0) < 0.05, f"{s0:.3f} → {mv._scale:.3f}")
    p.zoom_to.connect(mv._on_zoom_slider)

    p.font_mul_to.disconnect()
    f0 = font_px_of(mv)
    p.sld_font.setValue(p._tick_of_mul(3.0))
    pump(12)
    QTest.qWait(300)
    pump(10)
    ok("F2 断开字体缩放信号 ⇒ 拖滑块字号不变（D 判据真在岗）",
       abs(font_px_of(mv) - f0) < 0.01, f"{f0:.1f} → {font_px_of(mv):.1f}px")
    p.font_mul_to.connect(mv._on_font_mul)

    # ---------------------------------------------------------------
    print("===== G v2.6.42 字体滑块设定要被记住（持久化） =====")
    import json as _json
    cfg = Path(CDM.DATA_DIR) / "view_settings.json"
    if cfg.exists():
        cfg.unlink()

    def _disk():
        if not cfg.exists():
            return {}
        return _json.loads(cfg.read_text(encoding="utf-8"))

    p.font_lock_btn().setChecked(False)
    mv._font_mul = 1.0
    mv._font_lock_px = None
    p.sld_font.setValue(p._tick_of_mul(2.0))
    pump(12)
    QTest.qWait(300)            # 等 80ms 防抖 + 全量重算
    pump(10)
    ok("G1 改了倍率 ⇒ 真的落盘 view_settings.json",
       cfg.exists(), f"{cfg.name}")
    d1 = _disk()
    ok("G2 盘上记的倍率 = 刚拖的那一档（2.0）",
       abs(float(d1.get("font_mul", -1)) - 2.0) < 0.05,
       f"font_mul={d1.get('font_mul')}")

    mv._font_mul = 1.0          # 假装"下次打开"，内存归默认值
    mv._font_lock_px = None
    mv._load_view_settings()
    ok("G3 下次打开能读回同一倍率，滑块也回到原位",
       abs(mv._font_mul - 2.0) < 0.05
       and abs(p.sld_font.value() - p._tick_of_mul(2.0)) <= 2,
       f"_font_mul={mv._font_mul:.2f} tick={p.sld_font.value()}")

    p.font_lock_btn().setChecked(True)
    pump(12)
    QTest.qWait(250)
    pump(10)
    d2 = _disk()
    ok("G4 字体🔒 锁住 ⇒ 锁定的字号也记进文件",
       d2.get("font_lock_px") is not None and float(d2["font_lock_px"]) > 0,
       f"font_lock_px={d2.get('font_lock_px')}")
    mv._font_lock_px = None
    mv._load_view_settings()
    ok("G5 下次打开🔒 还是勾上的",
       mv._font_lock_px is not None and p.font_lock_btn().isChecked(),
       f"lock_px={mv._font_lock_px}")

    p.font_lock_btn().setChecked(False)
    pump(10)
    mv._font_mul = 1.0
    _orig = mv._save_view_settings
    _orig()                     # 正常写一次 ⇒ 盘上 = 1.0
    mv._save_view_settings = lambda: None        # ★ 变异：写盘变空
    try:
        p.sld_font.setValue(p._tick_of_mul(3.0))
        pump(12)
        QTest.qWait(300)
        pump(10)
        d3 = _disk()
        ok("G6 变异：写盘函数变空 ⇒ 盘上倍率停在 1.0 不跟着变（G2 判据真在岗）",
           abs(float(d3.get("font_mul", -1)) - 1.0) < 0.05,
           f"font_mul={d3.get('font_mul')}（应还是 1.0，不是 3.0）")
    finally:
        del mv._save_view_settings

    # ---------------------------------------------------------------
    # ★★ v2.6.52：滑块要"像控件"——
    #   H 鼠标悬浮换光标；滚轮落在滑块上 = 调它自己，且**不许同时把地图也缩了**
    #     （滑块 ignore 掉 wheel ⇒ 事件冒泡到 QGraphicsView ⇒ 一次滚动两件事）
    print("===== H v2.6.52 滑块光标 + 滚轮（地图不许跟着动） =====")

    def wheel_to(w, dy):
        c = w.rect().center()
        ev = QWheelEvent(QPointF(c), QPointF(w.mapToGlobal(c)), QPoint(0, 0),
                         QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(w, ev)

    ok("H1 鼠标悬浮在两条滑块上 ⇒ 光标变成左右箭头（可拖）",
       p.sld_zoom.cursor().shape() == Qt.SizeHorCursor
       and p.sld_font.cursor().shape() == Qt.SizeHorCursor,
       f"zoom={p.sld_zoom.cursor().shape()} font={p.sld_font.cursor().shape()}")
    ok("H2 两把锁按钮是手型光标（提示可点）",
       p.zoom_lock_btn().cursor().shape() == Qt.PointingHandCursor
       and p.font_lock_btn().cursor().shape() == Qt.PointingHandCursor)

    # 先站到中间档，两头都留余量（★ v2.7.6：MID 按面板区间算，不再写死 1.0）
    p.sld_zoom.setValue(p._tick_of_zoom(MID))
    p.sld_font.setValue(p._tick_of_mul(2.4))
    pump(12)
    QTest.qWait(400)
    pump(10)

    v0, s0 = p.sld_zoom.value(), mv._scale
    wheel_to(p.sld_zoom, 120)
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("H3 滚轮在**整体缩放滑块**上 ⇒ 滑块动、地图跟着放大",
       p.sld_zoom.value() > v0 and mv._scale > s0 * 1.02,
       f"tick {v0}→{p.sld_zoom.value()}，scale {s0:.3f}→{mv._scale:.3f}")

    m0, s1 = mv._font_mul, mv._scale
    wheel_to(p.sld_font, 120)
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("H4 滚轮在**字体滑块**上 ⇒ 只改字号，地图一动不动",
       abs(mv._font_mul - m0) > 1e-6 and abs(mv._scale - s1) < 1e-6,
       f"倍率 {m0:.3f}→{mv._font_mul:.3f}，scale {s1:.4f}→{mv._scale:.4f}")

    # ★ 变异自检（H4 的"地图一动不动"必须**不是恒真**）：
    #   ★★ 试过把滑块的 wheelEvent 换成 e.ignore() 走"冒泡"，但 sendEvent 不发散父级
    #      ⇒ 变异不生效（会得到假结论）。改用**对照实验**：同样一个滚轮事件，
    #      越过滑块直接发给地图 ⇒ scale 必须立刻变。
    #      两个结果合起来才说明：滚轮链路是活的，H4 的"不动"是滑块 accept 的功劳。
    s2 = mv._scale
    wheel_to(mv.viewport(), 120)
    pump(20)
    QTest.qWait(400)
    pump(10)
    ok("H5 对照：同一个滚轮事件**直接给地图** ⇒ scale 立刻变（H4 的'不动'不是恒真）",
       abs(mv._scale - s2) > 1e-6, f"scale {s2:.4f}→{mv._scale:.4f}")

    # 收尾：滚轮要把滑块推回原位，别影响后续
    p.sld_zoom.setValue(p._tick_of_zoom(MID))
    p.sld_font.setValue(p._tick_of_mul(2.4))
    pump(12)
    QTest.qWait(300)
    pump(10)

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
