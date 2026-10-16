# -*- coding: utf-8 -*-
"""
tools/_chk_tt_colstable.py
==========================
回归：**首末班车表格的列宽必须跨站恒定**（v2.6.12 修的老毛病）。

老毛病：`_compute_cols()` 按**当前站**的内容实测「线路」「方向」两列宽度
⇒ 右侧信息面板里**切换站点时列宽跟着变**，整个表格左右抖。
实测紧凑表：上塘 [44,72] → 上屋 [52,84] → 前海湾 [52,62]，单次最多跳 **22px**。

修法：改成**全量站点共用一份**（`global_col_widths()`，扫 379 站 1284 行
只算一次并缓存 ⇒ 列宽恒定；紧凑表总宽 350px 仍在面板可用 356px 之内）。

守三件事：
  A 不同站的 `COLS` **逐项相等**（跨站不跳）
  B 紧凑表 `sizeHint().width()` ≤ 面板可用宽 356（不横向溢出）
  C 变异：让全量扫描失效（返回 0 ⇒ 走"按当前内容实测"的兜底分支）⇒ A 必须失败
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

_TMP = Path(tempfile.mkdtemp(prefix="v2612cols_"))
for _n in ("stations.json", "lines.json"):
    if (CDM.DATA_DIR / _n).exists():
        shutil.copy(CDM.DATA_DIR / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication           # noqa: E402

import ui.timetable_editor as TE                     # noqa: E402
from ui.timetable_editor import TimetableEditor      # noqa: E402

PANEL_AVAIL = 356        # 右侧信息面板实测可用宽（与 _test_edit_dialog 同源）

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


def pick_stations(n: int = 6):
    """挑几个**线路数不同**的站（列宽最容易跟着变的就是它们）。"""
    dm_stations = CDM.get_data_manager().all_stations()
    by_n = {}
    for sid, s in dm_stations.items():
        tt = (s.get("timetable") or "").strip()
        if not tt:
            continue
        k = len(s.get("lines") or [])
        by_n.setdefault(k, (sid, tt))
    out = [by_n[k] for k in sorted(by_n)]
    return out[:max(n, 3)]


def main() -> int:
    app = QApplication(sys.argv)
    picks = pick_stations()
    print("\n===== A 列宽必须跨站恒定 =====")
    print("      样本：%s" % "、".join("%s(%d线)" % (sid, len(
        CDM.get_data_manager().all_stations()[sid].get("lines") or []))
        for sid, _tt in picks))

    for compact in (True, False):
        cols_list = []
        for sid, tt in picks:
            ed = TimetableEditor(tt, compact=compact)
            cols_list.append((sid, tuple(round(c, 2) for c in ed.COLS)))
        uniq = set(c for _s, c in cols_list)
        tag = "紧凑表(面板)" if compact else "完整表(弹窗)"
        check(f"{tag}：{len(picks)} 个站的列宽**逐项相等**（切站不跳）",
              len(uniq) == 1,
              "；".join("%s=%s" % (s, list(c)) for s, c in cols_list[:3])
              if len(uniq) > 1 else "统一 = %s" % (list(next(iter(uniq))),))

    print("\n===== B 紧凑表不许横向溢出 =====")
    worst = 0
    for sid, tt in picks:
        ed = TimetableEditor(tt, compact=True)
        worst = max(worst, ed.sizeHint().width())
    check("紧凑表 sizeHint ≤ 面板可用宽 %d" % PANEL_AVAIL,
          worst <= PANEL_AVAIL, f"最宽 {worst}px ≤ {PANEL_AVAIL}")

    print("\n===== C 变异自检：让全量扫描失效 =====")
    old_g = TE.global_col_widths
    TE.global_col_widths = lambda: (0.0, 0.0)   # ⇒ 走"按当前内容实测"的兜底分支
    cols_bad = []
    for sid, tt in picks:
        ed = TimetableEditor(tt, compact=True)
        cols_bad.append(tuple(round(c, 2) for c in ed.COLS))
    TE.global_col_widths = old_g
    check("变异（全量扫描失效、退回按当前内容）后列宽**不再统一** ⇒ A 判据真在上岗",
          len(set(cols_bad)) > 1,
          "变异后 %s" % sorted(set(cols_bad)))

    print("\n===== 结果：%d 通过 / %d 失败 =====" % (PASS, FAIL))
    for n in FAILED:
        print("  - " + n)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
