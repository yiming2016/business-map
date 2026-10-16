# -*- coding: utf-8 -*-
"""只读诊断：相邻两站**都有走廊替身点**时，会不会顶穿/叠在一起？

用户原话：「在两站都是换乘站的情况下，线路的轨道会出现严重变形」。

机制（`build_line_points_ex` 的 `through` 分支）：
  换乘站 A 有走廊 ⇒ 在站前后各插一个替身点：
      进站 P_in(A)  = A_off + u_A * sp_A * bp_A
      出站 P_out(A) = A_off + u_A * sn_A * bn_A
  其中 bp/bn = min(120, 0.45 × 邻站在走廊轴上的投影)。

★ 如果 A 和 B **相邻且都插了替身点**，就可能出现：
      A_off --P_out(A)-->            <--P_in(B)-- B_off
  两个替身点在中间**顶穿**甚至互相越过 ⇒ 线在站间打结、折返，就是用户说的
  "轨道严重变形"。站距越短越危险（黄贝岭→湖贝只有 115px，而替身点上限 120）。

判据（沿 A_off → B_off 的单位向量 ê 投影）：
      t_out = (P_out(A) - A_off)·ê        A 往 B 伸出多远
      t_in  = (B_off - P_in(B))·ê         B 往 A 伸出多远
      overlap = t_out + t_in - d          > 0 ⇒ 两段替身点重叠
      covered = (t_out + t_in) / d        覆盖了整段的几成

用法：
    python tools/_probe_pair_overlap.py
"""
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from ui.map_view import line_station_xy             # noqa: E402


def lanes_of(st, lid):
    d = (st.get("lanes") or {}).get(str(lid))
    if not d:
        return None
    try:
        if float(d[3]) < 3.0:
            return None
        return (float(d[0]), float(d[1]), round(float(d[2]) / 45.0) * 45.0)
    except (IndexError, TypeError, ValueError):
        return None


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    rows = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        n = len(seq)
        if n < 3:
            continue
        # 先算每个站在本线上的 (line_xy, off, u, P_in, P_out)
        info = {}
        for i, nm in enumerate(seq):
            s = st.get(nm) or {}
            x, y = line_station_xy(s, lid)
            ln = lanes_of(s, lid)
            info[i] = dict(name=nm, base=(x, y), lanes=ln, pine=None, poute=None)
            if ln is None or not (0 < i < n - 1):
                continue
            dx, dy, through = ln
            ox, oy = x + dx, y + dy
            ua = math.radians(through)
            ux, uy = math.cos(ua), math.sin(ua)
            px, py = line_station_xy(st.get(seq[i - 1]) or {}, lid)
            nx, ny = line_station_xy(st.get(seq[i + 1]) or {}, lid)
            tp = (px - x) * ux + (py - y) * uy
            tn = (nx - x) * ux + (ny - y) * uy
            sp = 1.0 if tp > 0 else -1.0
            sn = 1.0 if tn > 0 else -1.0
            if sp == sn:
                continue
            bp = min(120.0, 0.45 * abs(tp)) if abs(tp) > 1e-6 else 0.0
            bn = min(120.0, 0.45 * abs(tn)) if abs(tn) > 1e-6 else 0.0
            info[i]["off"] = (ox, oy)
            info[i]["u"] = (ux, uy)
            if bp >= 15.0:
                info[i]["pine"] = (ox + ux * sp * bp, oy + uy * sp * bp)
            if bn >= 15.0:
                info[i]["poute"] = (ox + ux * sn * bn, oy + uy * sn * bn)

        for i in range(1, n):
            A, B = info[i - 1], info[i]
            aoff = A.get("off") or A["base"]
            boff = B.get("off") or B["base"]
            d = math.hypot(boff[0] - aoff[0], boff[1] - aoff[1])
            if d < 1e-6:
                continue
            ex, ey = (boff[0] - aoff[0]) / d, (boff[1] - aoff[1]) / d
            t_out = 0.0
            if A.get("poute"):
                t_out = (A["poute"][0] - aoff[0]) * ex + (A["poute"][1] - aoff[1]) * ey
            t_in = 0.0
            if B.get("pine"):
                t_in = (boff[0] - B["pine"][0]) * ex + (boff[1] - B["pine"][1]) * ey
            # 负值 = 替身点往"远离对方"的方向伸（那是另一种病：甩反）
            bad_dir = (t_out < -1.0) or (t_in < -1.0)
            ov = t_out + t_in - d
            cov = (t_out + t_in) / d
            trA = len((st.get(A["name"]) or {}).get("lines") or []) > 1
            trB = len((st.get(B["name"]) or {}).get("lines") or []) > 1
            rows.append(dict(lid=lid, a=A["name"], b=B["name"], d=d, ov=ov,
                             cov=cov, t_out=t_out, t_in=t_in, bad=bad_dir,
                             both=(trA and trB),
                             hasA=bool(A.get("poute")), hasB=bool(B.get("pine"))))

    rows.sort(key=lambda r: -(r["ov"] / max(r["d"], 1.0)))
    print("段总数 %d；其中两端都插了替身点的 %d 段"
          % (len(rows), sum(1 for r in rows if r["hasA"] and r["hasB"])))
    print("\n替身点互相顶穿最狠的前 28 段（ov>0 = 重叠 px，cov = 被替身点盖住的段长比例）：")
    print("%-5s %-12s→%-12s %7s %7s %6s %7s %7s %-8s"
          % ("线", "上站", "下站", "段长", "重叠", "cov", "伸A", "伸B", "两站换乘"))
    for r in rows[:28]:
        if not (r["hasA"] or r["hasB"]):
            continue
        print("%-5s %-12s→%-12s %7.1f %7.1f %6.2f %7.1f %7.1f %-8s"
              % (r["lid"], r["a"], r["b"], r["d"], r["ov"], r["cov"],
                 r["t_out"], r["t_in"],
                 "两站都是" if r["both"] else ("仅前" if not r["hasA"] else "仅后")))
    real = [r for r in rows if r["hasA"] and r["hasB"] and r["ov"] > 0]
    print("\n★ 两端都插替身点且**真重叠**（ov>0）的段：%d 段" % len(real))
    for r in sorted(real, key=lambda z: -z["ov"])[:20]:
        print("   %-5s %-12s→%-12s 段长 %6.1f  重叠 %6.1f  盖住 %.0f%%  %s"
              % (r["lid"], r["a"], r["b"], r["d"], r["ov"], r["cov"] * 100,
                 "两站都是换乘站" if r["both"] else "（只有一端是换乘站）"))
    cov = [r for r in rows if r["cov"] > 1.02]
    print("\n覆盖比 >1.02 的段（替身点合计比段还长）：%d 段" % len(cov))
    return 0


if __name__ == "__main__":
    sys.exit(main())
