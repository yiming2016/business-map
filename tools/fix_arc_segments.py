# -*- coding: utf-8 -*-
"""给「官方是弧、但我们没描线」的段补上一条弧（消灭八向化掰出来的扭曲）。

背景：`tools/fix_octi_twist.py` 只能救**已经描过线**的段（那段有 `traced` 点列，
把标签换成 traceN 就能不八向化）。但"很多地方奇怪的扭曲"里还有一大批段
**根本没描过线** —— 它们走的是默认画法（两站直连 + 八向化），官方明明是弧，
八向化就把它掰成"45°斜线 + 一小段直线"，叠上圆角就是扭曲。

做法（每段三步，后两步都是护栏）：
  ① 拟合：`trace_assist.trace_smooth()` 沿官方点云 A* 走一遍，再按弧长分桶取中位
     ⇒ 一条贴着官方中心线的平滑折线；
  ② 自检：新折线离**官方中心线**的 p90 必须比"现在的画法"好 3px 以上，否则不改；
  ③ 只在"弧确实比八向化好"的段上动手（差的段一律保持原样）。

用法：
    python tools/fix_arc_segments.py            # 只看不动
    python tools/fix_arc_segments.py --apply    # 写入 traced（先备份 lines.json）
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"

from ui.map_view import build_line_points_ex, line_station_xy, octi_off_paths  # noqa: E402
from ui import metro_render as MR                    # noqa: E402
from ui import trace_assist as TA                    # noqa: E402

BETTER = 3.0          # 弧比现状至少好这么多像素才采纳
# 同色冲突线（官方几条线共用一个颜色）⇒ 点云/掩膜会串线，一律不碰
SAME_COLOR = {"2", "8", "4", "10", "16", "有轨电车", "有轨电车支线", "坪山云巴"}


def main():
    apply = "--apply" in sys.argv
    dm = CDM.get_data_manager()
    st = dm.all_stations()
    doc = dm.lines_doc
    traced = doc.setdefault("traced", {})
    off = set(doc.get("octi_off") or [])
    rows = []

    for L in (doc.get("lines") or []):
        lid = str(L.get("id"))
        if lid in SAME_COLOR or not TA.available():
            continue
        seq = [n for n in (L.get("stations") or []) if n in st]
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            key = "%s|%s|%s" % (lid, a, b)
            if key in traced:
                continue                     # 已描过的段交给 fix_octi_twist 管
            sa, sb = st.get(a), st.get(b)
            if not sa or not sb:
                continue
            ax, ay = line_station_xy(sa, lid)
            bx, by = line_station_xy(sb, lid)
            pts, ebl = build_line_points_ex(lid, [a, b], st)
            if len(pts) < 2:
                continue
            octi = [(p.x(), p.y()) for p, _s in MR.octilinear_waypoints_tagged(pts, ebl)]
            dev_now = TA.cloud_dev(lid, octi)
            line_pts = [(ax, ay), (bx, by)]
            dev_line = TA.cloud_dev(lid, line_pts)
            arc = TA.trace_smooth(lid, ax, ay, bx, by)
            if not arc:
                continue
            dev_arc = TA.cloud_dev(lid, line_pts[:1] + [tuple(p[:2]) for p in arc]
                                   + line_pts[1:])
            if dev_now is None or dev_arc is None:
                continue
            base = dev_now if dev_line is None else min(dev_now, dev_line)
            rows.append({
                "key": key, "lid": lid, "a": a, "b": b,
                "dev_now": dev_now, "dev_line": dev_line,
                "dev_arc": dev_arc, "gain": base - dev_arc,
                "n_octi": len(octi), "n_arc": len(arc),
                "arc": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in arc],
            })

    rows.sort(key=lambda r: -r["gain"])
    fixed = [r for r in rows if r["gain"] > BETTER]
    print("=" * 92)
    print("没描过线的段：官方是弧吗？（离官方中心线的 p90，越小越贴）")
    print("=" * 92)
    print("共审 %d 段（无描线、非同色线）" % len(rows))
    print("弧比现状好 > %.1fpx 的段：%d 段" % (BETTER, len(fixed)))
    if fixed:
        import statistics
        g = [r["gain"] for r in fixed]
        print("改善：中位 %.1fpx，最大 %.1fpx" % (statistics.median(g), max(g)))
    print("-" * 92)
    print("%-28s %8s %8s %8s %7s %s" % ("段", "现状", "直线", "弧", "改善", "点数"))
    for r in rows[:25]:
        print("%-28s %8.1f %8.1f %8.1f %+7.1f  %d→%d"
              % (r["key"], r["dev_now"],
                 -1 if r["dev_line"] is None else r["dev_line"],
                 r["dev_arc"], r["gain"], r["n_octi"], r["n_arc"]))

    if not apply:
        print("\n（只看不动；要写入请加 --apply）")
        return 0
    if not fixed:
        print("\n没有需要改的段。")
        return 0

    bak = DATA / ("lines.json.bak_arc_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    for r in fixed:
        traced[r["key"]] = r["arc"]
        off.add(r["key"])              # 顺带免掉八向化（两端也直连）
    doc["octi_off"] = sorted(off)
    tmp = DATA / "lines.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA / "lines.json")
    print("\n[OK] 已补 %d 段的弧（备份 %s）" % (len(fixed), bak.name))
    print("     traced 总数 %d，octi_off 总数 %d" % (len(traced), len(off)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
