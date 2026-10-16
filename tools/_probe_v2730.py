# -*- coding: utf-8 -*-
"""v2.7.30 探针：数字框"三位数打不进去"的根治 + 同类问题排查。

用户原话：「拖动余量到底能填写多少？每次我都无法输入三位数，重新检查相关问题并修复」

根因（本探针 ① 的判据就是它）：
    QSpinBox 是**逐字符**校验的。range 上限写死 400 时，键入 "500" 的最后一刻
    中间值 500 > 400 ⇒ 那个字符被吞掉、框里停在 50 ⇒ 用户看到"三位数输不进"。

判据一律**模拟真实键入**（QTest.keyClicks + 回车），不读静态 range 就下结论。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["METROEDITOR_NO_VIEW_START"] = "1"          # 别在跑回归时瘫刚看图模式
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # ★ 绝不弹窗到用户屏幕上

PASS = FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}  ({detail})")


def pump(n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


app = None


def type_into(spin, text: str) -> int:
    """像人一样把 text 逐字符敲进数字框、敲回车，返回最终落地的 value。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    spin.lineEdit().selectAll()
    pump(2)
    QTest.keyClicks(spin, text)
    QTest.keyClick(spin, Qt.Key_Return)
    pump(4)
    return int(spin.value())


def main() -> None:
    global app
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication(sys.argv)

    from ui.image_settings_dialog import ImageSettingsDialog, PAN_PAD_MAX

    d = tempfile.mkdtemp(prefix="probe_v2730_")

    # ------------------------------------------------------------------
    dlg = ImageSettingsDialog(None, {}, d)
    dlg.show()
    pump(10)

    # ---- ① 可填范围足够写三位数（这是"输不进去"的直接答案）----
    pad = dlg.sp_pan_pad
    ok("① 拖动余量上限 ≥ 999（三位数可填）", pad.maximum() >= 999,
       f"range = {pad.minimum()}..{pad.maximum()}")

    # ---- ② 真实键入：三位数、四位数都必须原样落地（不被吞字符）----
    for text in ("100", "500", "999", "1234"):
        dlg.sp_pan_pad.setValue(24)
        pump(2)
        got = type_into(pad, text)
        ok(f"② 拖动余量键入 {text} ⇒ 落地 {text}", got == int(text),
           f"实际={got}")

    # ---- ③ 面板宽度框同口径检查（minimum > 0，最容易歪的那一个）----
    iw = dlg.sp_info_w
    iw.setValue(520)
    pump(2)
    g500 = type_into(iw, "500")
    ok("③ 面板宽度键入 500 ⇒ 500", g500 == 500, f"={g500}")
    iw.setValue(520)
    pump(2)
    g999 = type_into(iw, "999")            # > 上限 ⇒ 保留原值，绝不能跳到下界 360
    ok("③b 面板宽度键入超限值 ⇒ 保留原值 520（不被拉到下限 360）",
       g999 == 520, f"={g999}（下界={iw.minimum()} 上界={iw.maximum()}）")

    # ---- ④ ★变异自检：把上限改回 400 ⇒ ② 的判据必须失效 ----
    old_max = pad.maximum()
    pad.setMaximum(400)
    pad.setValue(24)
    pump(2)
    bad = type_into(pad, "500")
    ok("④ ★变异自检：上限改回 400 ⇒ 键入 500 被打回 50（② 判据确实在抓这个病）",
       bad == 50, f"落地={bad}")
    pad.setMaximum(old_max)
    pad.setValue(24)
    pump(2)

    # ---- ⑤ 主窗口侧不再有第二道夹取（min(400, v) 的兜底）----
    from ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    pump(20)
    mv = win.map_view

    # 实时链路：⚙️ 改数字 ⇒ 立刻作用到地图
    dlg.pan_pad_changed.connect(win._on_pan_pad_live)
    pad.setValue(300)
    pump(8)
    ok("⑤ 改拖动余量 ⇒ 地图立刻拿到新值", abs(mv.pan_pad() - 300) < 0.5,
       f"mv.pan_pad()={mv.pan_pad()}")

    # 写进设置文件的值不被夹
    from ui.image_mode import load_settings, save_settings
    sec = load_settings(win._data_dir())
    sec["pan_pad_scene"] = 1500
    save_settings(win._data_dir(), sec)
    ok("⑤b 设置里写 1500 ⇒ 读回来还是 1500（不再被 min(400,…) 夹掉）",
       win._saved_pan_pad() == 1500, f"={win._saved_pan_pad()}")

    # ---- ⑥ ★变异自检：断开实时信号 ⇒ ⑤ 的判据必须失效 ----
    dlg.pan_pad_changed.disconnect(win._on_pan_pad_live)
    before = mv.pan_pad()
    pad.setValue(700)
    pump(8)
    ok("⑥ ★变异自检：断开信号后地图不再跟着变",
       abs(mv.pan_pad() - before) < 0.5, f"{before} → {mv.pan_pad()}")

    # ---- ⑦ 分钟框也走同一口径（越界不灾难）----
    #   ★前提：没勾「每隔」时这个框是**禁用**的（Qt 不接收键盘事件），
    #     探针模拟键入前必须先勾上 —— 否则测的是"禁用"，不是"输不进去"。
    mn = dlg.sp_min
    ok("⑦a 未勾「每隔」时分钟框是禁用的（设计如此，不是 bug）",
       not mn.isEnabled(), f"enabled={mn.isEnabled()}")
    dlg.cb_timer.setChecked(True)
    pump(4)
    mn.setValue(5)
    pump(2)
    ok("⑦b 勾上后可键入 30 ⇒ 30", type_into(mn, "30") == 30, f"={mn.value()}")
    ok("⑦c 键入 999 ⇒ 999（上限 240 时会被吞字符 ⇒ 已放宽到 1440）",
       type_into(mn, "999") == 999, f"={mn.value()} 上限={mn.maximum()}")

    print(f"\n探针结果：{PASS} 通过 / {FAIL} 失败")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                                  # noqa: BLE001
        import traceback
        traceback.print_exc()
        FAIL += 1
        print(f"\n探针异常终止：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
