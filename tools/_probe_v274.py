# -*- coding: utf-8 -*-
"""v2.7.4 探针：

  ① 右侧面板「首班 / 末班」的时间药丸**不再裁字** ——
     时间列宽按字号实测（`TT_TIME_PT` 11.5 粗体下 `23:59` 实测 41px），
     而不是写死 54。判据：列宽 ≥ 文字宽 + QSS 内耗（`TIME_W_CHROME`）。
     ★ 带变异自检：把列宽强行改回 54，判据必须变红（证明判据真在岗）。

  ② 「出入口信息」**恢复显示但只读**（用户：「你搞丢了不同出入口外的信息」
     →「只恢复『能看』」）：
       · 右侧面板 + 双击弹窗里都能看到 A/B/C/D 各出入口内容；
       · 控件只读、没有「＋ 添加出入口」；
       · ★ 数据层保险：`READONLY_UI_FIELDS` 让 `_collect()` 跳过这个键
         ⇒ 保存后 stations.json 里的 exits 一个字节都不变（这里实测往返）。
       · 「设施」仍然不显示（用户只要求出入口回来）。

跑法（offscreen，绝不抢焦点）：
    METROEDITOR_NO_ACTIVATE=1 python tools/_probe_v274.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtGui import QFont, QFontMetrics          # noqa: E402
from PySide6.QtWidgets import (QApplication, QLineEdit,  # noqa: E402
                               QPlainTextEdit)

app = QApplication(sys.argv)

from core.schema import EDITABLE_FIELDS, HIDDEN_UI_FIELDS, READONLY_UI_FIELDS  # noqa: E402
from ui.info_panel import InfoPanel                    # noqa: E402
from ui.exits_editor import ExitsEditor                # noqa: E402
from ui import timetable_editor as TTE                 # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + (("  " + str(extra)) if extra else ""))


def pump(n=8):
    for _ in range(n):
        app.processEvents()


# ============================================================
# ① 时间列不再裁字
# ============================================================
print("== ① 时间列宽度（首班 / 末班）==")

f_t = QFont(TTE.FONT_FAMILY)
f_t.setPointSizeF(TTE.TT_TIME_PT)
f_t.setBold(True)
_fm = QFontMetrics(f_t)
_text_w = _fm.horizontalAdvance("23:59")
_need = _text_w + TTE.TIME_W_CHROME
print("     字号 %.1fpt 粗体：'23:59' = %dpx，加内耗 %d ⇒ 需要 %dpx"
      % (TTE.TT_TIME_PT, _text_w, TTE.TIME_W_CHROME, _need))
ok("T1a 常量下限仍是 54（历史值，供对比）", TTE.COMPACT_TIME == 54,
   f"COMPACT_TIME={TTE.COMPACT_TIME}")
ok("T1b 实测需要宽度 **大于** 老的写死值 54（说明当年确实会裁）",
   _need > 54, f"需要 {_need} > 54")

w = MainWindow()
w.resize(1480, 900)
w.show()
pump(10)

if w.info_panel.isHidden():
    w.btn_info_toggle.click()
    pump(8)
w._on_station_clicked("世界之窗")
pump(10)

tt = w.info_panel._widgets.get("timetable")
ok("T1c 面板里有首末班表格", tt is not None)
if tt is not None:
    cols = list(tt.COLS)
    print("     COLS =", cols, " hint =", tt.sizeHint().width(),
          " 面板可用 =", w.info_panel.width())
    ok("T1d 时间列宽 ≥ 文字 + 内耗（不裁字）",
       cols[2] >= _need and cols[4] >= _need,
       f"时间列 {cols[2]}/{cols[4]} vs 需要 {_need}")
    ok("T1e 时间列是**按字号实测**出来的，不是写死的 54",
       cols[2] > 54, f"实测 {cols[2]} > 54")
    ok("T1f 加宽后整表仍塞得进面板（无横向溢出）",
       tt.sizeHint().width() < w.info_panel.width() - 20,
       f"hint {tt.sizeHint().width()} < 面板 {w.info_panel.width()}")

    # 像素级：药丸里的文字左右都要有留白（居中裁剪的话会贴边/缺角）
    pills = [c for c in tt.findChildren(QLineEdit)
             if c.objectName() in ("TTFirst", "TTLast") and c.geometry().x() > 0]
    ok("T1g 找得到时间药丸", len(pills) >= 4, f"共 {len(pills)} 颗")
    def _text_span(widget):
        """量药丸里**文字**的左右边界（物理像素）。

        ★★ 判据不能拿"非背景色"当文字 —— 药丸是圆角矩形（radius 8），
          四个角上露的是父背景（白/灰），会被当成内容 ⇒ 左边界恒为 0
          （第一版就是这么假报红的）。只认**深色文字像素**：
          首班文字 #1565C0（Σ=314）、末班 #C62828（Σ=278），
          两种药丸底色 Σ≥720 ⇒ 阈值 480 分得很开。
        ★ 只在**中间高度带**扫描，进一步避开圆角。
        """
        img = widget.grab().toImage()
        W, H = img.width(), img.height()
        y0, y1 = int(H * 0.30), int(H * 0.70)
        cols_px = []
        for x in range(W):
            n = 0
            for y in range(y0, y1):
                cc = img.pixelColor(x, y)
                if cc.red() + cc.green() + cc.blue() < 480:
                    n += 1
            cols_px.append(n)
        first = next((i for i, v in enumerate(cols_px) if v > 0), None)
        last = next((i for i in range(W - 1, -1, -1) if cols_px[i] > 0), None)
        return W, first, last

    def _pill_ok(widget):
        """一颗药丸是否"文字完整"。

        ★★ 两条判据缺一不可（第一版只有"左右留白"这一条，被变异骗过去了）：
          ① **文字跨度** ≥ 理论宽的 75% —— 居中裁剪时文字会被压成中间一小段，
             此时左右留白反而很宽，只看留白是抓不住的（实测变异后只剩 5px 文字）。
          ② 左右留白 ≥ 2 物理像素 —— 抓"第一个数字贴边/缺角"。
        """
        W, first, last = _text_span(widget)
        if first is None or last is None:
            return False, "找不到文字"
        dpr = widget.devicePixelRatioF()
        want = _fm.horizontalAdvance(widget.text()) * dpr
        span = last - first + 1
        gap_l, gap_r = first, W - 1 - last
        good = (span >= 0.75 * want) and gap_l >= 2 and gap_r >= 2
        return good, ("span=%d/期望%.0f 左%d 右%d" % (span, want, gap_l, gap_r))

    bad = []
    for c in pills:
        good, why = _pill_ok(c)
        if not good:
            bad.append((c.text(), why))
    ok("T1h 每颗时间药丸文字完整（跨度够 + 左右不贴边）", not bad,
       f"异常={bad}" if bad else f"{len(pills)} 颗全部通过")

    # ★ 变异自检（像素级）：把药丸的左右内边距撑大 ⇒ 文字可用宽度不够 ⇒
    #   居中被裁 ⇒ 像素判据必须变红。
    #   ★ 为什么不用 `setFixedWidth(40)` 做变异：药丸在网格里，网格列有
    #     `setColumnMinimumWidth`，下一次布局会把宽度**拉回** 61 ⇒ 变异假生效
    #     （第一版就是这么假通过的：压到 40 后量出来还是 左9 右14）。
    #     改内边距不动布局，QLineEdit 自己的绘制区立刻变窄，必被裁。
    if pills:
        _p = pills[0]
        _old_qss = _p.styleSheet()
        _p.setStyleSheet(_old_qss.replace("padding: 2px 5px",
                                          "padding: 2px 26px"))
        pump(4)
        _mut_good, _mut_why = _pill_ok(_p)
        ok("T1h2 变异（内边距撑大 ⇒ 文字居中裁剪）⇒ 像素判据必须变红",
           not _mut_good, _mut_why)
        _p.setStyleSheet(_old_qss)
        pump(4)
        _back_good, _back_why = _pill_ok(_p)
        ok("T1h3 还原内边距后判据又变绿", _back_good, _back_why)

    # ★ 变异自检：把时间列强行改回 54，判据必须变红
    _old = list(tt.COLS)
    tt.COLS = [_old[0], _old[1], 54, _old[3], 54]
    tt._compute_cols()
    mut_cols = list(tt.COLS)
    # 变异后应回到能算出 54 的口径（_compute_cols 里会 max(_time_need)，
    # 所以这里直接把常量也临时改掉才是真变异）
    TTE.COMPACT_TIME = 54
    _saved_need = TTE.TimetableEditor._time_need
    TTE.TimetableEditor._time_need = lambda self: 54      # noqa: E731
    tt._compute_cols()
    mut_cols = list(tt.COLS)
    ok("T1i 变异（列宽退回 54）⇒ 判据必须失败",
       not (mut_cols[2] >= _need), f"变异后时间列 = {mut_cols[2]} vs 需要 {_need}")
    TTE.TimetableEditor._time_need = _saved_need          # 还原
    tt._compute_cols()
    ok("T1j 还原后时间列又够宽", list(tt.COLS)[2] >= _need, f"{tt.COLS}")

# ============================================================
# ② 出入口：只读展示
# ============================================================
print("== ② 出入口信息（v2.7.5：可编辑；详细判据在 _probe_v275）==")

ok("T2a 「出入口信息」已从隐藏集合里移出",
   "exits" not in HIDDEN_UI_FIELDS, str(HIDDEN_UI_FIELDS))
# ★ v2.7.5：`exits` 又**改回可编辑**了（用户：「A、B、C 作为按钮，点击后可以
#   输入进行编辑，详细信息也应该为输入框」）⇒ 只读集合已清空。
#   出入口的详细判据搬到了 `tools/_probe_v275.py`，这里只做冒烟级确认。
ok("T2b 它已从只读集合里移出（v2.7.5 起可编辑）",
   "exits" not in READONLY_UI_FIELDS, str(READONLY_UI_FIELDS))
ok("T2c 「设施」仍然隐藏（用户没要求回来）",
   "facilities" in HIDDEN_UI_FIELDS, str(HIDDEN_UI_FIELDS))

_doc = json.loads((Path(TTE.__file__).resolve().parent.parent
                   / "data" / "stations.json").read_text(encoding="utf-8"))
_st = _doc["stations"] if isinstance(_doc, dict) and "stations" in _doc else _doc
_raw_exits = str((_st.get("世界之窗") or {}).get("exits") or "")
ok("T2d 数据里这个站确实有出入口内容", len(_raw_exits) > 20, f"{len(_raw_exits)} 字")

ip = w.info_panel
ex = ip._widgets.get("exits")
ok("T2e 右侧面板里出入口控件回来了", ex is not None)
ok("T2f 它是可编辑控件（ExitsEditor.readonly=False）",
   isinstance(ex, ExitsEditor) and ex.readonly is False)

if isinstance(ex, ExitsEditor):
    tag_eds = [r[0] for r in ex.rows]
    txt_eds = [r[1] for r in ex.rows]
    ok("T2g 内容真的显示出来了（行数 ≥ 1）", len(ex.rows) >= 1,
       f"{len(ex.rows)} 行")
    # ★ v2.7.5：编号是**按钮**（ExitTagChip），不是输入框 —— 只查"详细信息"
    #   那一栏是否可编辑；编号的可编辑性由按钮点击切换保证（见 _probe_v275）。
    ok("T2h 详细信息是可编辑输入框（不是只读文本）",
       len(txt_eds) > 0 and all(not b.isReadOnly() for b in txt_eds))
    ok("T2i 「＋ 添加出入口」回来了", ex._add_btn is not None)
    # 显示内容要和原始数据对得上（A/B/C/D 各口都在）
    shown = ex.text()
    n_orig = len([1 for ln in _raw_exits.splitlines() if ln.strip()])
    n_show = len([1 for ln in shown.splitlines() if ln.strip()])
    ok("T2j 显示的行数 = 原始行数（没吞内容）", n_show == n_orig,
       f"显示 {n_show} / 原始 {n_orig}")
    ok("T2k 提到的出入口字母也一致",
       sorted(set(__import__("re").findall(r"[A-Z]\d*出入口", _raw_exits)))
       == sorted(set(__import__("re").findall(r"[A-Z]\d*出入口", shown))))

    # ★ v2.7.5：面板 _collect() **要**带 exits（改回可编辑 ⇒ 用户改了就得存）
    payload = ip._collect()
    ok("T2l 面板 _collect() 带上了 exits（可编辑就该保存）",
       "exits" in payload, f"keys={sorted(payload.keys())[:6]}…")

# 双击弹窗同理
from ui.edit_dialog import EditDialog                  # noqa: E402
dlg = EditDialog("世界之窗")
pump(10)
ex2 = dlg._widgets.get("exits")
ok("T2m 双击弹窗里出入口控件也回来了", ex2 is not None)
if isinstance(ex2, ExitsEditor):
    ok("T2n 弹窗里同样可编辑", ex2.readonly is False)
    ok("T2o 弹窗里也有「＋ 添加出入口」", ex2._add_btn is not None)
    p2 = dlg._collect()
    ok("T2p 弹窗 _collect() 带上了 exits",
       "exits" in p2, f"keys={sorted(p2.keys())[:6]}…")
ok("T2q 弹窗里「设施」没有控件（仍隐藏）",
   dlg._widgets.get("facilities") is None)
dlg.close()

# ★ 端到端往返：**一字未动**地喂进去再拼回，必须一字节不差（"没动过的行原样吐回"）
_mut = ExitsEditor(_raw_exits)
ok("T2r 出入控件 text() 拼回 == 原始文本（零改写）",
   _mut.text() == _raw_exits,
   "" if _mut.text() == _raw_exits else "%r != %r" % (_mut.text()[:60], _raw_exits[:60]))

# 空数据的站：可编辑态给一行空行，方便直接补
_empty = ExitsEditor("")
ok("T2s 空数据的站给一行空行 + 添加按钮",
   _empty._add_btn is not None and len(_empty.rows) == 1,
   f"rows={len(_empty.rows)}")

# ============================================================
TOTAL = len(PASS) + len(FAIL)
print("\n==== v2.7.4 探针：%d/%d 通过，%d 失败 ====" % (len(PASS), TOTAL, len(FAIL)))
if FAIL:
    print("失败项：", FAIL)
    sys.exit(1)
print("ALL PASS")
