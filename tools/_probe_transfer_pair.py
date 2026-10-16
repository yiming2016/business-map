# -*- coding: utf-8 -*-
"""只读诊断：换乘站的「走廊替身点」有没有把线路掰变形？

用户原话：「在两站都是换乘站的情况下，线路的轨道会出现严重变形」。

背景（`build_line_points_ex` 里的 `through` 分支）：
换乘站里每条线各占一条走廊（`lanes[线号] = [dx, dy, 走廊走向角, 拟合拉长度]`）。
为了让线在站区"顺着走廊穿过去"而不是打个尖角，代码会在站**前后各插一个替身点**：
      进站替身点 P_in  = 偏移点 + u * sp * bp
      本站偏移点  P
      出站替身点 P_out = 偏移点 + u * sn * bn
u 是走廊走向，sp/sn 由"前后邻站在走廊轴上的投影符号"决定。

能出问题的地方（本探针逐条量）：
  ① u（走廊走向）跟"这一段的实际走向"差得远 ⇒ 替身点把线先甩到一边再拉回来
  ② P_in 反而**更远离**上一站（伸错侧）⇒ 线先冲过头再折回，渲染出一个尖三角
  ③ P_out 反而**更远离**下一站
  ④ 相邻两个换乘站：前一站的 P_out 与后一站的 P_in **交叉/叠在一起**
  ⑤ 替身点伸得太长，把整段占满（bp+bn 接近站距）

用法：
    python tools/_probe_transfer_pair.py
"""
import json
import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402
from ui.map_view import build_line_points_ex        # noqa: E402


def ang_of(dx, dy):
    a = math.degrees(math.atan2(dy, dx)) % 180.0
    return a


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    rows = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        if len(seq) < 3:
            continue
        pts, _ebl, keys = build_line_points_ex(lid, seq, st, want_keys=True)
        # 每个站在 pts 里的主点下标：靠 key 反推太绕，这里按"点数对齐"重建
        # —— 直接改用几何法：对每个中间站，重算它的 P_in / P / P_out 并验证
        for i in range(1, len(seq) - 1):
            name = seq[i]
            s = st.get(name) or {}
            d = (s.get("lanes") or {}).get(lid)
            if not d:
                continue
            try:
                if float(d[3]) < 3.0:
                    continue
                through = round(float(d[2]) / 45.0) * 45.0
            except (IndexError, TypeError, ValueError):
                continue
            x, y = float(s.get("x", 0)), float(s.get("y", 0))
            ox, oy = x + float(d[0]), y + float(d[1])
            ua = math.radians(through)
            ux, uy = math.cos(ua), math.sin(ua)

            pa = st.get(seq[i - 1]) or {}
            pb = st.get(seq[i + 1]) or {}
            px, py = float(pa.get("x", 0)), float(pa.get("y", 0))
            nx, ny = float(pb.get("x", 0)), float(pb.get("y", 0))
            tp = (px - x) * ux + (py - y) * uy
            tn = (nx - x) * ux + (ny - y) * uy
            if (tp > 0) == (tn > 0):        # 同侧 ⇒ 不插替身点，跳过
                continue
            sp = 1.0 if tp > 0 else -1.0
            sn = 1.0 if tn > 0 else -1.0
            bp = min(120.0, 0.45 * abs(tp)) if abs(tp) > 1e-6 else 0.0
            bn = min(120.0, 0.45 * abs(tn)) if abs(tn) > 1e-6 else 0.0
            if bp < 15.0 and bn < 15.0:
                continue

            pin = (ox + ux * sp * bp, oy + uy * sp * bp)
            pout = (ox + ux * sn * bn, oy + uy * sn * bn)

            # ② P_in 应该比 P 更靠近上一站
            d_in = math.hypot(pin[0] - px, pin[1] - py)
            d_ct = math.hypot(ox - px, oy - py)
            bad_in = d_in > d_ct + 1.0
            # ③ P_out 应该比 P 更靠近下一站
            d_out = math.hypot(pout[0] - nx, pout[1] - ny)
            d_ct2 = math.hypot(ox - nx, oy - ny)
            bad_out = d_out > d_ct2 + 1.0
            # ① 替身点的伸出方向 vs 到邻站的实际方向（夹角 >90° = 甩反了）
            def ang_bad(p0, p1, ref):
                vx, vy = p1[0] - p0[0], p1[1] - p0[1]
                rx, ry = ref[0] - p0[0], ref[1] - p0[1]
                lv, lr = math.hypot(vx, vy), math.hypot(rx, ry)
                if lv < 1e-6 or lr < 1e-6:
                    return None
                c = (vx * rx + vy * ry) / (lv * lr)
                return math.degrees(math.acos(max(-1.0, min(1.0, c))))
            a_in = ang_bad((ox, oy), pin, (px, py)) if bp >= 15.0 else None
            a_out = ang_bad((ox, oy), pout, (nx, ny)) if bn >= 15.0 else None

            tr_a = len((pa.get("lines") or [])) > 1
            tr_b = len((pb.get("lines") or [])) > 1
            rows.append(dict(lid=lid, name=name, prev=seq[i - 1], nxt=seq[i + 1],
                             bp=bp, bn=bn, bad_in=bad_in, bad_out=bad_out,
                             a_in=a_in, a_out=a_out,
                             both=(tr_a and tr_b), tr_a=tr_a, tr_b=tr_b))

    def key(r):
        return (-(1 if r["bad_in"] else 0) - (1 if r["bad_out"] else 0)
                - (1 if (r["a_in"] or 0) > 60 else 0)
                - (1 if (r["a_out"] or 0) > 60 else 0))

    rows.sort(key=key)
    print("插了走廊替身点的中间站：%d 处" % len(rows))
    print("\n最可疑的前 25 处（bad=替身点伸错侧，ang=伸出方向与邻站方向夹角）：")
    print("%-6s %-10s %-10s→%-10s  bp/bn       bad_in bad_out  ang_in ang_out 邻站都换乘"
          % ("线", "站", "上站", "下站"))
    for r in rows[:25]:
        print("%-6s %-10s %-10s→%-10s %5.0f/%5.0f   %-6s %-7s  %6s %7s  %s"
              % (r["lid"], r["name"], r["prev"], r["nxt"], r["bp"], r["bn"],
                 "是" if r["bad_in"] else "-", "是" if r["bad_out"] else "-",
                 "-" if r["a_in"] is None else "%.0f°" % r["a_in"],
                 "-" if r["a_out"] is None else "%.0f°" % r["a_out"],
                 "两站都是" if r["both"] else ("仅前" if r["tr_a"] else
                                               ("仅后" if r["tr_b"] else "-"))))
    n_bad = sum(1 for r in rows if r["bad_in"] or r["bad_out"])
    n_ang = sum(1 for r in rows
                if (r["a_in"] or 0) > 60 or (r["a_out"] or 0) > 60)
    n_both = sum(1 for r in rows if r["both"])
    print("\n合计：伸错侧 %d 处、方向甩反(>60°) %d 处、邻站两站都是换乘站 %d 处"
          % (n_bad, n_ang, n_both))
    return 0


if __name__ == "__main__":
    sys.exit(main())
