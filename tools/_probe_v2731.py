# -*- coding: utf-8 -*-
"""v2.7.31 探针：看图模式下「拖动余量」必须真的生效。

用户原话：「你认为现在应该填写多少才能避免右侧被接触到？我填写了很多数值
不起作用，是否逻辑上出现什么问题」

★ 逻辑问题（本探针的结论）：
  `_refresh_scene_rect()` 在图模式下把 sceneRect **锁死成那张位图的范围**、不外扩。
  要让内容退到面板左侧，视口右边界必须能到「位图右边 + 面板宽度 + pad」，
  而滚动条 range 锁死 ⇒ 那个位置根本不存在 ⇒ 不管 pad 填几都拖不过去。

  实测（1480×900 窗口、右侧面板 520px、v2.7.30）：
      编辑模式  pad=0/24/400/3000 ⇒ 内容右端 x = 944 / 941 / 896 / 583   ✅ 在动
      看图模式  pad=0/24/400/3000 ⇒ 内容右端 x = 1212 / 1212 / 1212 / 1212 ❌ 纹丝不动
      （面板左沿 x=958 ⇒ 看图模式下内容实打实钻在面板底下 254px）

★ 语义纠正：pad 是**保护距离**，不是放开量。pad 越大 ⇒ 元素离边缘越远。
  pad=0 = 元素最多贴到面板边缘（想要"完全不被碰到"，填 0 就够）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = FAIL = 0
app = None
PANEL_W = 520          # 模拟右侧「站点详情」面板宽度


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}  ({detail})")


def pump(n: int = 4) -> None:
    for _ in range(n):
        app.processEvents()


def drag_right(mv) -> None:
    """一路往右拖到拉不动为止（符号照抄真实 mouseMoveEvent 的用法）。"""
    from PySide6.QtCore import QPointF
    sb = mv.horizontalScrollBar()
    for _ in range(400):
        d = mv._pan_limit_delta(QPointF(-100.0, 0.0))
        if abs(d.x()) < 0.3:
            break
        # ★ 整数滚动条别把尾量吃掉：|d|<1 时也走满 1px，否则会停在半途，
        #   累积出几像素的"假失败"（我们最初就是被这个坑了一次）。
        step = int(d.x()) if abs(d.x()) >= 1 else (1 if d.x() > 0 else -1)
        before = sb.value()
        sb.setValue(sb.value() - step)
        pump(1)
        mv._refresh_scene_rect()          # ★ 真实拖动不会调，但 Qt 会按 sceneRect 重算 range
        if sb.value() == before:
            break


def right_edge_px(mv, base):
    """内容（元素 / 位图）最右点此刻落在屏幕哪个 x 上。"""
    from PySide6.QtCore import QPointF
    return mv.mapFromScene(QPointF(base.right(), base.top())).x()


def measure(mv, base, pad) -> float:
    from PySide6.QtCore import QRectF
    mv.set_pan_pad(pad)
    if getattr(mv, "_view_mode", False):
        mv._view_rect = QRectF(base)
    mv._refresh_scene_rect()
    mv.horizontalScrollBar().setValue(mv.horizontalScrollBar().minimum())
    pump(2)
    drag_right(mv)
    pump(3)
    return right_edge_px(mv, base)


def main() -> None:
    global app
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRectF
    app = QApplication(sys.argv)

    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(20)
    mv = win.map_view
    vp = mv.viewport()
    mv.set_view_insets(0, PANEL_W)          # 右侧面板开着
    base = mv._elements_rect()
    limit = vp.width() - PANEL_W            # 面板左沿的屏幕 x
    print(f"视口={vp.width()}x{vp.height()} scale={mv._scale:.4f} "
          f"面板左沿 x={limit} 内容宽={base.width():.0f}")

    # ---- ① 看图模式：pad 必须真的起作用（这是本轮的主病）----
    mv._view_mode = True
    v0 = measure(mv, base, 0)
    v200 = measure(mv, base, 200)
    v600 = measure(mv, base, 600)
    ok("① 看图模式：不同 pad ⇒ 内容右端位置不同（pad 真的生效了）",
       abs(v200 - v0) > 4 and abs(v600 - v200) > 4,
       f"pad 0/200/600 ⇒ x={v0:.0f} / {v200:.0f} / {v600:.0f}")

    # ---- ② pad=0 就已经不被右侧面板碰到 ----
    ok("② 看图模式 pad=0 ⇒ 内容最右点停在面板左沿以左（不再钻到面板底下）",
       v0 <= limit + 6, f"内容右端 x={v0:.0f} 面板左沿={limit}")

    # ---- ③ 语义：pad 越大越保守（元素离边缘更远）----
    ok("③ pad 越大 ⇒ 元素离面板越远（这是保护距离，不是放开量）",
       v200 < v0 and v600 < v200,
       f"{v0:.0f} → {v200:.0f} → {v600:.0f}")
    want = v0 - 600 * mv._scale
    ok("③b pad=600 的位移量符合预期（≈ pad × 缩放）",
       abs(v600 - want) <= 10, f"实测 {v600:.0f} 期望 {want:.0f}")

    # ---- ④ 编辑模式保持同样校准（别修一边坏一边）----
    mv._view_mode = False
    mv._refresh_scene_rect()
    e0 = measure(mv, base, 0)
    e600 = measure(mv, base, 600)
    ok("④ 编辑模式 pad=0 ⇒ 内容右端仍停在面板左沿以左",
       e0 <= limit + 6, f"x={e0:.0f} 面板左沿={limit}")
    ok("④b 编辑模式 pad 越大也越保守", e600 < e0 - 4, f"{e0:.0f} → {e600:.0f}")

    # ---- ⑤ 拖到极端不能把画面拖成全白（旧 ↺ 回归）----
    mv._view_mode = True
    mv._view_rect = QRectF(base)
    mv.set_pan_pad(600)
    mv._refresh_scene_rect()
    mv.horizontalScrollBar().setValue(mv.horizontalScrollBar().minimum())
    pump(2)
    drag_right(mv)
    pump(3)
    from PySide6.QtCore import QPointF
    left_x = mv.mapFromScene(QPointF(base.left(), base.top())).x()
    ok("⑤ 拖到极限后画面里仍有内容（没被拖成全白屏）",
       left_x < vp.width() and right_edge_px(mv, base) > 0,
       f"内容左端 x={left_x:.0f} 右端 x={right_edge_px(mv, base):.0f} 视口={vp.width()}")

    # ---- ⑥ ★变异自检：看图模式 sceneRect 重新锁死 ⇒ ① 必须失效 ----
    mv.scene_.setSceneRect(QRectF(base))               # 假装没做 v2.7.31 的外扩
    held = mv._refresh_scene_rect

    def _locked(self=mv, _r=None, _s=None):            # noqa: ANN001
        pass                                            # 任何刷新都不许改 sceneRect
    mv._refresh_scene_rect = _locked
    m0 = measure_locked(mv, base, 0)
    m600 = measure_locked(mv, base, 600)
    ok("⑥ ★变异自检：sceneRect 锁死（= v2.7.30 的老行为）⇒ pad 重新失效",
       abs(m600 - m0) <= 2, f"pad 0/600 ⇒ x={m0:.0f} / {m600:.0f}")
    mv._refresh_scene_rect = held

    print(f"\n探针结果：{PASS} 通过 / {FAIL} 失败")


def measure_locked(mv, base, pad) -> float:
    """同 measure()，但**不许**刷新 sceneRect —— 模拟 v2.7.30 的老行为。"""
    from PySide6.QtCore import QRectF
    mv.set_pan_pad(pad)
    mv._view_rect = QRectF(base)
    mv.horizontalScrollBar().setValue(mv.horizontalScrollBar().minimum())
    pump(2)
    drag_right(mv)
    pump(3)
    return right_edge_px(mv, base)


if __name__ == "__main__":
    try:
        main()
    except Exception:                                   # noqa: BLE001
        import traceback
        traceback.print_exc()
        FAIL += 1
        print(f"\n探针异常终止：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
