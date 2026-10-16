# -*- coding: utf-8 -*-
"""只读探针：自动追踪（甲）抽出来的路径到底像不像官方走廊？

对每条线每个相邻站对跑 `trace_assist.trace()`，报：
  · 成功率（走不通的要能说清是哪些段）
  · 路径长 / 直线距离 的比值（>1.5 说明绕远了，多半是同色线串线了）
  · 路径上每个点到本线中心线的最远距离（**这是核心**：贴得住才叫描对了）
"""
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402

from ui import trace_assist as TA                   # noqa: E402


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    print("点云可用 =", TA.available())
    t0 = time.time()
    tot = ok = 0
    worst_ratio = []
    worst_off = []
    per_line = {}
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        n_ok = n_tot = 0
        mx_off = 0.0
        mx_ratio = 0.0
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            sa, sb = st[a], st[b]
            n_tot += 1
            pts = TA.trace(lid, float(sa["x"]), float(sa["y"]),
                           float(sb["x"]), float(sb["y"]))
            if not pts:
                worst_ratio.append((lid, a, b, "走不通"))
                continue
            n_ok += 1
            # 长度比
            ln = 0.0
            for k in range(1, len(pts)):
                ln += ((pts[k][0] - pts[k - 1][0]) ** 2
                       + (pts[k][1] - pts[k - 1][1]) ** 2) ** 0.5
            stt = ((float(sb["x"]) - float(sa["x"])) ** 2
                   + (float(sb["y"]) - float(sa["y"])) ** 2) ** 0.5
            ratio = ln / max(stt, 1e-6)
            mx_ratio = max(mx_ratio, ratio)
            if ratio > 2.0:
                worst_ratio.append((lid, a, b, "长度比 %.2f" % ratio))
            # 贴不贴得住：路径每个点到本线中心线的距离
            for (px, py) in pts:
                dv = TA.deviation(lid, px, py)
                if dv is not None and dv > mx_off:
                    mx_off = dv
            if mx_off > 24:
                worst_off.append((lid, a, b, "离中心线 %.0f" % mx_off))
        tot += n_tot
        ok += n_ok
        per_line[lid] = (n_ok, n_tot, mx_ratio, mx_off)
        print("%-6s 段 %3d/%-3d  最长比 %.2f  离中心线最远 %.0f"
              % (lid, n_ok, n_tot, mx_ratio, mx_off))
    print("\n合计 %d/%d 段  %.1f%%  用时 %.1fs" % (ok, tot, 100.0 * ok / max(tot, 1),
                                                 time.time() - t0))
    if worst_ratio:
        print("\n长度比异常（前 12）：", worst_ratio[:12])
    if worst_off:
        print("离中心线超标（前 12）：", worst_off[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
