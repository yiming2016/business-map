# -*- coding: utf-8 -*-
"""删掉描线路径两端"贴着站点的小倒钩"。

用户原话：「很多地方都有奇怪的扭曲」。除了八向化把弧掰成台阶，还有第二种：
描线是 A* 从站点附近起步的，**偶尔会先往站点反方向勾一小段再折回来**
（实测 11号线 前海湾→南山：A=(944,5098)，描线首点 (944,5072) 在站**下方** 26px，
接着 (944,5390) 又往下走 ⇒ 一条 26px 的边配 173.2° 折角 = 接站处的小倒钩，
`_chk_transfer_pair` 的"短边急折"就是它）。

判据：渲染器本来就会把两端的**站点坐标**接上，所以离站点 < SNAP 的首/末点
几乎没用（顶多 45px 的走廊），删掉它反而更干净。**只删首/末**，中间的绝不动。
删完自检：离官方中心线的 p90 不许变差超过 3px。

★★ v2.6.63 返工：**删完必须把新的首/末点吸附回"走廊落脚点"**。
    第一版只删不接，结果 36 段描线的末端离落脚点 100~295px，超过
    `_traced_fresh()` 的 90px 容忍 ⇒ **整段描线被判过期、退回直线**
    （13|光明城|德雅路 离官方像素 3.2 → 61.8px）。
    ⇒ 现在的做法：删完立刻把首/末点写成落脚点，保证描线永远接得上。

用法：
    python tools/fix_trace_end_snap.py            # 只看不动
    python tools/fix_trace_end_snap.py --apply    # 写入（先备份）
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

from ui.map_view import line_station_xy               # noqa: E402
from ui import trace_assist as TA                    # noqa: E402

SNAP = 45.0     # 离站点这么近的首/末点 = 倒钩/无用点，删掉
WORSE_OK = 3.0  # 删掉后离官方中心线最多允许变差多少
# ★ v2.6.63：几乎**贴着落脚点**的点（<= NEAR px）删掉几乎不改变形状，
#   但它会留下一条 <35px 的短边 ⇒ `_chk_transfer_pair` 的"短边急折"就是它
#   （实测 14|岗厦北|黄木岗：首点离落脚点 25.7px，配 46.2° 转角）。
#   这种点放宽 dev 容忍到 NEAR_WORSE（视觉优先）—— 差 3px 在 8000px 的图上
#   根本看不出来，一个 25px 的急折倒钩反而扎眼。
NEAR = 30.0
NEAR_WORSE = 8.0


def foot(st, lid):
    """走廊落脚点（与 build_line_points_ex 里 `_traced_fresh` 用的是同一个点）。

    描线路径的两端**必须**落在这里，否则整段会被判过期。
    """
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
    off = set(doc.get("octi_off") or [])
    rows = []

    for key, tp in list(traced.items()):
        if not isinstance(tp, (list, tuple)) or len(tp) < 3:
            continue
        parts = str(key).split("|")
        if len(parts) != 3:
            continue
        lid, a, b = parts
        sa, sb = st.get(a), st.get(b)
        if not sa or not sb:
            continue
        ax, ay = foot(sa, lid)      # ★ 落脚点，不是站中心
        bx, by = foot(sb, lid)
        P = [(float(p[0]), float(p[1])) for p in tp
             if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(P) < 3:
            continue
        Q = list(P)
        cut = []
        hook = False

        def _cos(u, v):
            lu = (u[0] * u[0] + u[1] * u[1]) ** 0.5
            lv = (v[0] * v[0] + v[1] * v[1]) ** 0.5
            if lu < 1e-6 or lv < 1e-6:
                return 1.0
            return (u[0] * v[0] + u[1] * v[1]) / (lu * lv)

        # ★ 首端：连着删，直到离站 > SNAP（但至少留 2 个点）
        #   ★★ "倒钩" = 站点→该点 的方向 与 该点→下一点 的方向**几乎相反**
        #      （cos < -0.87 即夹角 >150°）。这种点画出来就是接站处一小段反向的
        #      线（实测 11号线 车公庙→福田：26px 的边配 173.2° 折角），
        #      **视觉扭曲**，哪怕删了离官方略远也该删。
        while len(Q) > 2:
            d = ((Q[0][0] - ax) ** 2 + (Q[0][1] - ay) ** 2) ** 0.5
            if d >= SNAP:
                break
            if _cos((Q[0][0] - ax, Q[0][1] - ay),
                    (Q[1][0] - Q[0][0], Q[1][1] - Q[0][1])) < -0.87:
                hook = True
            cut.append(("首", round(d, 1), Q[0]))
            Q.pop(0)
        while len(Q) > 2:
            d = ((Q[-1][0] - bx) ** 2 + (Q[-1][1] - by) ** 2) ** 0.5
            if d >= SNAP:
                break
            if _cos((Q[-1][0] - Q[-2][0], Q[-1][1] - Q[-2][1]),
                    (bx - Q[-1][0], by - Q[-1][1])) < -0.87:
                hook = True
            cut.append(("末", round(d, 1), Q[-1]))
            Q.pop()
        if not cut:
            continue
        # ★★ 删完之后**把落脚点补回两端**（★ 是"插入"不是"替换"：
        #    替换 Q[0] 会把紧挨着它的那个点也丢掉，实测 1|鲤鱼门|大新 dev
        #    13.6 → 33.2px，白白变差）。补回去之后首/末点一定落在落脚点上
        #    ⇒ 描线永远接得上，不会被 `_traced_fresh` 判过期。
        Q2 = list(Q)
        if ((Q2[0][0] - ax) ** 2 + (Q2[0][1] - ay) ** 2) ** 0.5 > 0.5:
            Q2.insert(0, (round(ax, 1), round(ay, 1)))
        if ((Q2[-1][0] - bx) ** 2 + (Q2[-1][1] - by) ** 2) ** 0.5 > 0.5:
            Q2.append((round(bx, 1), round(by, 1)))
        Q = Q2
        dev_old = TA.cloud_dev(lid, [(ax, ay)] + P + [(bx, by)])
        dev_new = TA.cloud_dev(lid, [(ax, ay)] + Q + [(bx, by)])
        ok_dev = (dev_old is None or dev_new is None
                  or dev_new <= dev_old + WORSE_OK)
        if hook:
            ok_dev = True          # ★ 真倒钩：视觉优先，删（不卡 dev）
        elif max(c[1] for c in cut) <= NEAR:
            # ★ 几乎贴着落脚点的点：删掉只为消掉那条 <35px 的短边
            ok_dev = (dev_old is None or dev_new is None
                      or dev_new <= dev_old + NEAR_WORSE)
        rows.append({"key": key, "cut": cut, "n": (len(P), len(Q)),
                     "dev": (dev_old, dev_new), "ok": ok_dev, "hook": hook,
                     "new": [[round(x, 1), round(y, 1)] for x, y in Q]})

    rows.sort(key=lambda r: -max(c[1] for c in r["cut"]))
    print("=" * 90)
    print("描线两端「贴站小倒钩」（离站 < %.0fpx 的首/末点）" % SNAP)
    print("=" * 90)
    print("命中 %d 段（其中在 octi_off 名单里的 %d 段）"
          % (len(rows), sum(1 for r in rows if r["key"] in off)))
    for r in rows[:20]:
        c = max(r["cut"], key=lambda t: t[1])
        print("  %-24s %s端 %.1fpx  点 %d→%d  离底图 %.1f→%.1f  %s%s"
              % (r["key"], c[0], c[1], r["n"][0], r["n"][1],
                 r["dev"][0] or -1, r["dev"][1] or -1,
                 "倒钩·必删" if r.get("hook") else "",
                 "" if r["ok"] else "变差·跳过"))

    good = [r for r in rows if r["ok"]]
    if not apply:
        print("\n（只看不动；要写入请加 --apply）")
        return 0
    if not good:
        print("\n没有可安全删的。")
        return 0
    bak = DATA / ("lines.json.bak_snapend_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    for r in good:
        traced[r["key"]] = r["new"]
    tmp = DATA / "lines.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA / "lines.json")
    print("\n[OK] 已删 %d 段的端部倒钩（备份 %s）" % (len(good), bak.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
