# -*- coding: utf-8 -*-
"""v2.6.84-u11：用户点名四段走廊的描线修复。

用户原话：「下梅林➡️梅村；高新南➡️红树湾南➡️神湾(=深湾)；老街➡️晒布；岗头➡️双拥街」

体检结论（fix_fit_official --line 3/9/10）：
  3|老街|晒布        有描线但偏 p90=5.4 max=7.0
  9|下梅林|梅村      有描线但是 2 点直线，偏 p90=4.0
  9|高新南|红树湾南  有描线，偏 p90=8.6 max=11.0（段级锚位/肘部病）
  9|红树湾南|深湾    有描线，偏 p50=3.0 p90=5.0
  10|上李朗→凉帽山→甘坑→雪象→岗头   全部 MISSING（八向化兜底在画）

修法分两相：
  相1（3/9 号线 4 段）＝ fix_fit_user9 的桥接 A* 机器原样复用，只换目标清单。
  相2（10 号线 4 段）＝ fix_traced_line10 的 trace_assist 点云 A*（10 号线与
     4 号线同色 #E01010，官方色掩膜法整线失效，只能走点云）。

写盘：两相都只写 软件/data/lines.json（U.DATA 的 JSON dump，不调 dm.save()）。
★ 跑之前必须：关 exe → 软件/data 同步到 源码/data（已做，md5 一致）。
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fix_fit_user9 as U
import fix_fit_official as F

# ---------- 相 1：桥接 A*（复用 fix_fit_user9 全套机器 + 真实渲染自检） ----------
MASK_TARGETS = [
    "3|老街|晒布",
    "9|下梅林|梅村",
    "9|高新南|红树湾南",
    "9|红树湾南|深湾",
    # ★ 10 号线官方真色是粉 (247,117,148)，色表里的 #E01010 是错的。
    #   修正 FR.COLORS 后掩膜法可用 ⇒ 一并进相 1（桥接 A*）。
    "10|雪象|岗头",
    "10|岗头|华为",
    "10|上李朗|凉帽山",
    "10|凉帽山|甘坑",
    "10|甘坑|雪象",
]

# ---------- 相 2：10 号线点云 A*（复用 fix_traced_line10 配方） ----------
LID10 = "10"
L10_SEQ = ["上李朗", "凉帽山", "甘坑", "雪象", "岗头"]
L10_TRIM = 12.0          # 站贴走廊时掐 12px（45 会把弯掐光，v2.6.82 教训）
L10_RDP = 4.0            # 定案 eps=2~5
L10_DEV_MAX = 30.0       # 质检：每点离 10 号线点云的最大距离


def phase1():
    U.TARGETS = list(MASK_TARGETS)
    return U.main()


def phase2():
    """备用点云相：10 号线已并入相 1（粉色掩膜），此相保留但跳过重复目标。"""
    import math
    import core.data_manager as CDM
    from ui import trace_assist as TA

    skip = set(MASK_TARGETS)
    todo = ["%s|%s|%s" % (LID10, a, b) for a, b in zip(L10_SEQ, L10_SEQ[1:])]
    todo = [k for k in todo if k not in skip]
    if not todo:
        print("=" * 70)
        print("相 2：无可做目标（10 号线已由相 1 处理）")
        return 0
    print("=" * 70)
    print("相 2：点云 A* %s" % todo)
    print("dm 实际数据路径:", CDM.DATA_DIR)
    DOC = U.DOC
    ST = F.ST
    traced = DOC.setdefault("traced", {})
    got = 0
    for key in todo:
        a, b = key.split("|")[1], key.split("|")[2]
        ra, rb = ST.get(a), ST.get(b)
        if not ra or not rb:
            print("[SKIP] %s：站点缺失" % key)
            continue
        ax, ay = float(ra["x"]), float(ra["y"])
        bx, by = float(rb["x"]), float(rb["y"])
        g = TA._graph(LID10)
        raw = None
        if g is not None:
            na = g.nearest(ax, ay, TA.SNAP_MAX)
            nb = g.nearest(bx, by, TA.SNAP_MAX)
            if na is not None and nb is not None:
                ids = g.astar(na[0], nb[0])
                if ids:
                    raw = [g.pts[i] for i in ids]
                    while len(raw) > 1 and math.hypot(
                            raw[0][0] - ax, raw[0][1] - ay) < L10_TRIM:
                        raw.pop(0)
                    while len(raw) > 1 and math.hypot(
                            raw[-1][0] - bx, raw[-1][1] - by) < L10_TRIM:
                        raw.pop()
        if not raw:
            print("[SKIP] %s：A* 走不通" % key)
            continue
        pts = TA._post(raw, L10_RDP)
        devs = []
        for p in pts:
            _d = TA.deviation(LID10, p[0], p[1])
            devs.append(999.0 if _d is None else _d)   # 0.0 是真值！
        dmax = max(devs)
        davg = sum(devs) / len(devs)
        span = math.hypot(bx - ax, by - ay)
        ok = dmax <= L10_DEV_MAX
        old = traced.get(key)
        traced[key] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in pts]
        if not ok and old is not None:
            traced[key] = old          # 质检不过就不覆盖旧值
        else:
            got += 1
        print("[%s] %s 点数=%d 段长=%.0fpx 离点云 avg=%.1f max=%.1f" % (
            "OK  " if ok else "WARN", key, len(pts), span, davg, dmax))

    if got:
        tmp = U.DATA / "lines.json.tmp"
        tmp.write_text(json.dumps(DOC, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(U.DATA / "lines.json")
        print("[写入] %s（含相 1 结果）" % (U.DATA / "lines.json"))
    else:
        print("[提示] 相 2 无新写入（相 1 已自行落盘）")
    return 0


def main():
    # ★ 修正官方 10 号线颜色（色表错值 #E01010 → 官方带实测粉色）
    import fix_retrace_from_official as _FR
    _e = _FR.COLORS.get("10")
    if isinstance(_e, dict):
        _e["colors"] = [[(247, 117, 148), 999]]
    else:
        _FR.COLORS["10"] = {"colors": [[(247, 117, 148), 999]]}
    print("[色表] 10 号线官方色 → (247,117,148)")

    bak = U.DATA / ("lines.json.bak_u11_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(U.DATA / "lines.json", bak)
    print("[备份] %s" % bak.name)
    rc = phase1()
    phase2()
    return rc


if __name__ == "__main__":
    sys.exit(main())
