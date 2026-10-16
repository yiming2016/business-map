# -*- coding: utf-8 -*-
"""把描线路径的**两端**重新吸附到"走廊落脚点"。

为什么需要（v2.6.63 返工）：
    `fix_trace_end_snap.py` 清"贴站小倒钩"时，把描线**首/末点**也一起删了
    （它们离站 < 45px）。删完之后路径末端就不再贴站了 ——
    实测 13|光明城|德雅路 的末点离德雅路落脚点 **156px**，而
    `_traced_fresh()` 的容忍是 **90px** ⇒ 整段描线被判"过期" ⇒ 退回直线
    （离官方像素 61.8px，本来是 3.2px）。

    也就是说：清倒钩把一批描线段整段废掉了。

做法：
    对每条描线，取两端的"走廊落脚点"（= 站坐标 + lanes 偏移，跟
    `build_line_points_ex` 里 `_traced_fresh(_tp, _a.x(), _a.y(), ox, oy)`
    用的完全同一个点），若原首/末点离它 < SNAP 就把首/末点**替换**成它
    （不新增也不删除中间点）。

用法：
    python tools/fix_trace_snap_align.py            # 只看不动
    python tools/fix_trace_snap_align.py --apply    # 写入（先备份）
"""
import json
import math
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

from ui.map_view import line_station_xy              # noqa: E402

SNAP = 250.0        # 首/末点离落脚点这么近就吸附（超过 ⇒ 站点真被拖走了，不动）
FRESH = 90.0        # 与 _traced_fresh 的 tol 一致，用来统计"已经过期"的段


def foot(st, lid):
    """走廊落脚点：站坐标 + lanes[line_id] 的前两个偏移。"""
    x, y = line_station_xy(st, lid)
    d = (st.get("lanes") or {}).get(str(lid))
    if d:
        try:
            return float(x) + float(d[0]), float(y) + float(d[1])
        except (IndexError, TypeError, ValueError):
            pass
    return float(x), float(y)


def main():
    apply = "--apply" in sys.argv
    dm = CDM.get_data_manager()
    st = dm.all_stations()
    doc = dm.lines_doc
    traced = doc.get("traced") or {}
    lines = doc.get("lines") or []

    # 先建「段 → 两端落脚点」的索引
    feet = {}
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            feet["%s|%s|%s" % (lid, a, b)] = (foot(st[a], lid), foot(st[b], lid))

    rows = []
    for key, path in traced.items():
        f = feet.get(key)
        if not f:
            continue
        if not path or len(path) < 2:
            continue
        (ax, ay), (bx, by) = f
        try:
            p0 = (float(path[0][0]), float(path[0][1]))
            pn = (float(path[-1][0]), float(path[-1][1]))
        except (TypeError, ValueError, IndexError):
            continue
        d0 = math.hypot(p0[0] - ax, p0[1] - ay)
        dn = math.hypot(pn[0] - bx, pn[1] - by)
        if max(d0, dn) <= FRESH:
            continue                      # 本来就接得上
        rows.append({
            "key": key, "d0": d0, "dn": dn,
            "snap0": 0.0 < d0 <= SNAP, "snapn": 0.0 < dn <= SNAP,
            "n": len(path),
        })

    rows.sort(key=lambda r: -max(r["d0"], r["dn"]))
    n_ok = sum(1 for r in rows if r["snap0"] or r["snapn"])
    print("=" * 88)
    print("描线两端离「走廊落脚点」超过 %.0fpx（= 会被 _traced_fresh 判过期）的段" % FRESH)
    print("=" * 88)
    print("共 %d / %d 段描线，其中过期 %d 段，可吸附修复 %d 段"
          % (len(traced), len(feet), len(rows), n_ok))
    print("%-32s %-10s %-10s %s" % ("段", "首点", "末点", "点数"))
    for r in rows[:30]:
        print("%-32s %9.1f %9.1f   %d%s"
              % (r["key"], r["d0"], r["dn"], r["n"],
                 "" if (r["snap0"] or r["snapn"]) else "   ← 超过吸附范围，跳过"))

    if not apply:
        print("\n（只看不动；要写入请加 --apply）")
        return 0
    if not n_ok:
        print("\n没有需要修的段。")
        return 0

    bak = DATA / ("lines.json.bak_snapalign_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    fixed = 0
    for r in rows:
        if not (r["snap0"] or r["snapn"]):
            continue
        key = r["key"]
        path = [list(p) for p in traced[key]]
        (ax, ay), (bx, by) = feet[key]
        if r["snap0"]:
            path[0] = [round(ax, 1), round(ay, 1)]
        if r["snapn"]:
            path[-1] = [round(bx, 1), round(by, 1)]
        traced[key] = path
        fixed += 1
    doc["traced"] = traced
    tmp = DATA / "lines.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA / "lines.json")
    print("\n[OK] 已吸附 %d 段（备份 %s）" % (fixed, bak.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
