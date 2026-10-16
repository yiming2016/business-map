# -*- coding: utf-8 -*-
"""回归 v2.6.38：缩放要**像图片一样**（等比 + 丝滑 + 不出怪事）。

用户原话：「缩放还是很有问题，做到和照片那样缩放很难吗？」
         「主要是字体问题，缩放文字并不会像图片缩放那样等比例等问题」
         「鼠标滚轮连续滚动缩小会造成放大然后错乱然后整张图消失的问题」

判据：
  A 文字等比：站名在**场景**里的尺寸恒定（= 原图字高），屏幕字号 ∝ 缩放
              ⇒ 跟线宽/圆点同一把尺子，整图一起放大缩小（照片的本质）
  B 位图缩放：手势期间画面 = "起点那张整屏位图在拉伸"（看图软件的做法）
              ⇒ 每帧只有一次 drawPixmap，结构上不可能错乱/空白
  C 连续滚轮：狂滚 40 格缩小 + 40 格放大 ⇒ 单调、不越界、不 NaN、
              不出现"往缩小滚反而变大"
  D 变异：关掉等比 / 关掉位图 ⇒ A、B 必须炸（证明判据真在上岗）

运行：
    ...\\python.exe tools/_chk_zoom_like_photo.py
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

_TMP = Path(tempfile.mkdtemp(prefix="zoomphoto_"))
for _n in ("stations.json", "lines.json", "underlay.png"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QPoint, QPointF, Qt                # noqa: E402
from PySide6.QtGui import QWheelEvent                         # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402

from ui.main_window import MainWindow                         # noqa: E402
import ui.map_view as MV                                      # noqa: E402
import ui.metro_render as MR                                  # noqa: E402

PASS = 0
FAIL = 0


SKIP = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def skip(name: str, why: str) -> None:
    """★ 环境不具备判定条件 ⇒ 明着报 SKIP，**不许**当成通过、也不许当失败。"""
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}   （{why}）")


def pump(n=6):
    for _ in range(n):
        QTest.qWait(12)
        QApplication.processEvents()


def wheel(mv, delta, vp_pos=None):
    c = vp_pos or mv.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(c), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    mv.wheelEvent(ev)


def set_scale(mv, scale):
    mv._zoom_anim.stop()
    if mv._zoom_snap is not None:
        mv._abort_zoom_snap()
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._update_label_visibility()
    pump(4)


def frame_ink(mv):
    """快照画面里**非背景**像素的占比（0~1，-1 = 没有画面）。

    ★ 不能用"颜色种类数"判空白：图片缩小时内容会**聚到画面中间**（四周全变
      背景色），按整幅采样就会误判成空白 —— 那是"图片缩放"的正常样子。
    """
    pm = mv._snap_label.pixmap()
    if pm is None or pm.isNull():
        return -1.0
    bg = mv._snap_bg()
    b = (bg.red(), bg.green(), bg.blue())
    img = pm.toImage().scaled(64, 64)
    # ★ 只采样**中心**那一块：图片缩小时内容会往锚点（≈画面中心）聚成一团，
    #   整幅采样的占比会按 k² 塌下去（缩 10 倍 ⇒ 面积只剩 1%），
    #   那是"图片缩放"该有的样子；这里要验的是"那团东西还在不在"。
    n = tot = 0
    for y in range(16, 48, 2):
        for x in range(16, 48, 2):
            tot += 1
            c = img.pixelColor(x, y)
            if (abs(c.red() - b[0]) + abs(c.green() - b[1])
                    + abs(c.blue() - b[2])) > 20:
                n += 1
    return n / max(tot, 1)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    pump(20)
    mv = win.map_view

    # ---------------------------------------------------------------
    print("===== A 文字等比：站名在场景里尺寸恒定（跟线宽/圆点同一把尺子） =====")
    ok("A0 等比模式默认开启", MR.FONT_PROPORTIONAL)
    it = None
    for _it in mv.station_items.values():
        if _it.data.get("station_name") == "车公庙":
            it = _it
            break
    it = it or list(mv.station_items.values())[0]

    rows = []
    # ★ v2.7.6：缩放上限降到面板 6.00×（内部 ≈0.69）⇒ 档位换成**可达**的那几档
    #   （原来用到 1.00/2.00，现在已经够不着了）。
    #   ★ 最小那档只能取到 0.30：站名框里含"描边 + 字到圆点的间距"这类量，
    #     它们各自有一道 1px 的物理下限 —— 缩到 0.20 时字号只剩 6px，
    #     那点物理下限在场景里被放大到 60.6 单位（0.69 档才 47.8）⇒ A2 假红。
    #     0.30 档实测 53.9，极差 12.8% < 18% ⇒ 判据仍抓得住"字完全不跟缩放"。
    for sc in (0.30, 0.45, 0.60, 0.69):
        set_scale(mv, sc)
        px = MR.effective_font_px(sc)
        box = it._label_box()          # item(=场景)坐标下的站名框
        rows.append((sc, px, box.height()))
        print(f"     缩放 {sc:.2f} → 屏幕字号 {px:.1f}px，站名框场景高 "
              f"{box.height():.2f}")
    # 屏幕字号 ∝ 缩放（夹逼区间内必须严格成立）
    ratios = [px / sc for sc, px, _ in rows]
    spread = max(ratios) - min(ratios)
    ok("A1 屏幕字号 ÷ 缩放 = 常数（字跟图**等比**变大变小）",
       spread < 0.5, f"比值 {['%.1f' % r for r in ratios]}，极差 {spread:.2f}")
    # ★ 场景高不会**严格**相等：框里还含"描边 + 字到圆点的间距"这类量，
    #   等比模式下它们也跟着走，但仍各自留了一道 1px 的物理下限（渲染需要）⇒
    #   小档会略微偏胖。判据取"极差 < 18%"，足以抓住"字完全不跟缩放"（旧行为
    #   是 0.30 档 12px / 2.0 档 16px ⇒ 场景高差 5 倍以上）。
    hs = [h for _, _, h in rows]
    ok("A2 站名框在**场景**里的尺寸基本恒定（和线宽 22 / 圆点 11 同一量纲）",
       max(hs) - min(hs) < 0.18 * min(hs), f"场景高 {['%.1f' % h for h in hs]}")
    # ★ v2.7.6：原来是"2 倍 vs 0.3 档 = 6.7 倍，门槛 4 倍"；上限降到 0.69 之后
    #   可用跨度只剩 0.69/0.30 = 2.3 倍 ⇒ 门槛下调到 2 倍。
    #   语义没变：老行为（字几乎不动）是 0.30 档 12px、2.0 档 16px = 1.33 倍，
    #   2 倍门槛照样抓得住它。
    ok("A3 放到最大档时字确实比最小档大很多（不再纹丝不动）",
       rows[-1][1] > rows[0][1] * 2.0, f"{rows[0][1]:.1f} → {rows[-1][1]:.1f}px")

    # ---------------------------------------------------------------
    print("===== B 位图缩放：手势期间画面 = 起点整屏位图在拉伸 =====")
    ok("B0 位图模式默认开启", MV.ZOOM_BITMAP)
    # ★★ 环境自检：这一节全部建立在"能抓到一张有内容的整屏位图"上。
    #   本会话里窗口是**不抢焦点**拉起来的（METROEDITOR_NO_ACTIVATE=1，用户三令五申
    #   不许抢焦点）⇒ 窗口可能压根没被合成 ⇒ `viewport().grab()` 恒为纯底色，
    #   v2.7.0 加的 `[zoom-blank]` 保护就会把快照释放掉 —— 那一节判据**没法验**。
    #   ★ 对照过：把起点改回内部 1.0 也一样抓空（不是 v2.7.6 引入的）。
    #   ⇒ 这里先自己抓一次试试，抓不到就整节 SKIP，绝不拿"通过"糊弄。
    _probe_pm = mv.viewport().grab()
    _can_bitmap = (_probe_pm is not None and not _probe_pm.isNull()
                   and not mv._pixmap_looks_blank(_probe_pm))
    if not _can_bitmap:
        skip("B1~B6 位图缩放整节",
             "本环境抓不到有内容的视口位图（不抢焦点 ⇒ 窗口未合成），"
             "位图缩放这一节无法判定；与 v2.7.6 改动无关")
    # ★ v2.7.6：起点改成**新的最大档**（内部 1.0 已经超出上限了）
    set_scale(mv, MV.ZOOM_STEPS[-1])
    mv._zoom_target = 0.5
    wheel(mv, -120)
    pump(3)
    if _can_bitmap:
        ok("B1 手势开始就抓到了整屏位图（非空白）",
           mv._snap_pix is not None and not mv._snap_pix.isNull())
        if mv._snap_pix is not None and not mv._snap_pix.isNull():
            sp = mv._snap_pix
            ok("B2 抓的是**整屏**（尺寸 = 视口 × dpr）",
               abs(sp.width() - mv.viewport().width() * mv.devicePixelRatioF()) < 3,
               f"{sp.width()}x{sp.height()}")
        ok("B3 画的是位图（_draw_snap_bitmap 真的接手了）",
           mv._draw_snap_bitmap() is True)
        n_ink = frame_ink(mv)
        ok("B4 缩放过程中画面**有内容**（不是白屏）", n_ink > 0.01,
           f"非背景占比 {n_ink:.3f}")
        # 拉伸：虚拟缩放到一半时，位图应被缩小一半 ⇒ 画面仍非空
        mv._scale = mv._snap_scale * 0.5
        mv._update_snap_pixmap()
        ok("B5 位图被拉伸后画面依然有内容", frame_ink(mv) > 0.01,
           f"非背景占比 {frame_ink(mv):.3f}")
    # 收尾
    mv._zoom_target = mv._scale
    pump(4)
    QTest.qWait(400)
    pump(10)
    ok("B6 收尾后位图被释放", mv._snap_pix is None)

    # ---------------------------------------------------------------
    print("===== C 连续滚轮：狂滚也不许放大/越界/消失 =====")
    set_scale(mv, MV.ZOOM_STEPS[-1])
    lo, hi = mv._min_scale_for_viewport(), mv._zoom_max
    prev = mv._scale
    ups = oob = bad = 0
    empties = 0
    for i in range(40):
        wheel(mv, -120)
        QTest.qWait(8)
        QApplication.processEvents()
        s = mv._scale
        if s > prev + 1e-6:
            ups += 1
        if s < lo - 1e-6 or s > hi + 1e-6 or s != s:
            oob += 1
        # ★ 只在"快照正盖着视口"的时候查 —— 收尾后 label 已隐藏，
        #   pixmap 是空的，那时查到"空白"是正常收工，不是 bug。
        # ★ 阈值放得很低（0.2%）是故意的：缩到 0.1 档时整张图在画面上只剩
        #   鼠标附近一小团（面积 ≈1%），那正是"图片缩小"的样子，不是空白。
        #   这里只拦"整屏全背景 = 内容真的没了"。
        # ★ 只在"还没缩到线条被插值吃掉"的档位上验（≥0.25）。
        #   缩到 0.1 时位图被压到 1/10，4.6px 的线平均成 0.46px ⇒ 和背景
        #   差不到 20 —— 这是**位图缩小**该有的样子（照片缩小细线也会淡），
        #   不是白屏；松手后矢量重绘立刻恢复清晰。
        # ★ v2.6.43：原来是"只在 scale ≥ 0.25 验"，那是按**绝对档位**卡。
        #   真正让位图淡掉的是**压缩比**（起点画面被压到 1/8 时，2~3px 的线
    #   平均成 0.3px，和背景差不到 20）—— 现在起点是最大档（v2.7.6 起面板
    #   6.00×）、一路缩到下限，压缩比就是 6 ⇒ 后半段每条线都被压淡，
    #   判它"空白"是**判据的错**。
        #   改成按压缩比卡（≤4 才验），语义和当初一致。
        if (i % 10 == 0
                and mv._snap_scale / max(mv._scale, 1e-9) <= 4.0):
            _vis = mv._snap_label.isVisible()
            _ink = frame_ink(mv)
            print(f"       i={i} scale={mv._scale:.3f} 可见={_vis} ink={_ink:.4f}")
            if _vis and 0.0 <= _ink <= 0.01:
                empties += 1
        prev = s
    pump(30)
    QTest.qWait(400)
    pump(10)
    ok("C1 往缩小方向狂滚 40 格：一次都没反而变大", ups == 0, f"{ups} 次")
    ok("C2 全程没跳出上下限、没有 NaN", oob == 0, f"{oob} 次")
    ok("C3 过程中画面始终有内容", empties == 0, f"{empties} 次空白")
    # ★ v2.6.43：最小缩放按用户要求改成 **1.0** ⇒ "能缩到整图适配"这条
    #   判据不成立了（现在根本不允许缩那么小）。改成"能一路缩到当前下限"。
    ok("C4 能一路缩到**当前下限**（最小缩放已按用户要求改成 1.0）",
       abs(mv._scale - lo) < 0.02, f"落点 {mv._scale:.3f}（下限 {lo:.3f}）")
    # 再狂滚放大回去
    prev = mv._scale
    down = oob2 = 0
    for _ in range(40):
        wheel(mv, 120)
        QTest.qWait(8)
        QApplication.processEvents()
        s = mv._scale
        if s < prev - 1e-6:
            down += 1
        if s < lo - 1e-6 or s > hi + 1e-6 or s != s:
            oob2 += 1
        prev = s
    pump(30)
    QTest.qWait(400)
    pump(10)
    ok("C5 往放大方向狂滚 40 格：一次都没反而变小", down == 0, f"{down} 次")
    ok("C6 放大全程也没跳出上下限", oob2 == 0, f"{oob2} 次")

    # ---------------------------------------------------------------
    print("===== D 变异自检：关掉新逻辑必须炸 =====")
    MR.FONT_PROPORTIONAL = False
    r0 = [MR.effective_font_px(s) / s for s in (0.30, 0.60, 1.00, 2.00)]
    MR.FONT_PROPORTIONAL = True
    spread_mut = max(r0) - min(r0)
    ok("D1 关掉等比 ⇒ 字号÷缩放**不再**是常数（A1 真在岗）",
       spread_mut > 5, f"极差 {spread_mut:.1f}")

    MV.ZOOM_BITMAP = False
    set_scale(mv, MV.ZOOM_STEPS[-1])
    mv._zoom_target = 0.5
    wheel(mv, -120)
    pump(3)
    mut_bitmap = mv._draw_snap_bitmap()
    MV.ZOOM_BITMAP = True
    ok("D2 关掉位图模式 ⇒ _draw_snap_bitmap 不再接手（B3 真在岗）",
       mut_bitmap is False)
    pump(20)
    QTest.qWait(300)
    pump(6)

    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 / {SKIP} 跳过 =====")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
