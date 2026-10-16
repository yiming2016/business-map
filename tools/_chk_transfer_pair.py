# -*- coding: utf-8 -*-
"""回归：走廊替身点会不会把线路掰出一个"陡峭的小台阶"？

用户原话：「在两站都是换乘站的情况下，线路的轨道会出现严重变形」。

背景：换乘站的每条线各占一条走廊（`lanes = [dx, dy, 走向角, 拟合度]`）。
为了让线在站区"顺着走廊穿过去"而不是打个尖角，`build_line_points_ex` 会在
站前后各插一个**替身点**（进站 P_in、出站 P_out），长度 = min(120, 0.45×投影)。

★ 病因（v2.6.56 修）：相邻两站**都**插替身点时，两端各算各的 ⇒ 加起来能盖住
  90% 段长，只剩十几像素自由段；两条走廊的横向错位（几十像素的测量误差级）
  全挤在那十几像素里 ⇒ 一个 45° 急折。实测 12 号线 国展→国展北：
  段长 197、两端各伸 92、自由段 12.5px、错位 12px ⇒ 45° 急折。

判据（只盯**真正画出来的点列形状**，不抄实现、也不猜 `ebl` 的含义）：
  ★ 先说两个踩过的坑：
    ① 抄实现 —— 第一版探针自己又写了一遍 `0.45×投影`，所以源码改了它也看不出
       变化（"验证工具自己写一遍 ⇒ 改坏了也验不出来"）。
    ② 猜 `ebl==""` 的含义 —— `""` 有两个来源：走廊直穿的边，**以及** `elbow_sides`
       表里值为空串的普通段。于是"覆盖比"量出 1.04 这种假数（2 号线 后海→科苑）。
    结论：判据只许盯**点的坐标与几何关系**。

  A1 折点扎堆：段内相邻两个"显著折点"（转角 > TURN_MIN）之间不得近于 GAP_MIN
     —— 这就是"两条平行走廊错位时，两个折点被挤在一起"的直接刻画
  A2 短边急折：任何顶点，若两侧较短的一条边 < SHORT px，它的转角不得超过 MAXTURN
  B  变异自检：把替身点比例放回 1.0（旧行为）⇒ A1 必须**失败**
     （判据不失败 = 判据是假的）

用法：
    python tools/_chk_transfer_pair.py
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

SHORT = 35.0        # 边长小于这个就算"短边"（OCTI_TOL_PX=26 以内的偏差会被直接连）
MAXTURN = 25.0      # 短边上允许的最大转角（度）
TURN_MIN = 20.0     # 转角大于这个才算"显著折点"
GAP_MIN = 35.0      # 两个相邻显著折点之间的距离下限
MAXGAP = 40.0       # 一个"折段"里最多允许几个显著折点（超过就是来回扭）

PY = sys.executable
METRIC_TAG = "##METRIC##"


def collect(st, lines):
    """返回每段的 (lid, a, b, 该段的点列表, 该段每条边的 ebl, 段长, 是否两站都换乘)

    ★ 口径不许猜：`build_line_points_ex` 里 `ebl[k] == ""` 就是**走廊直穿的那条边**
      （P_in→P、P→P_out 都标 ""），其余是自由边。第一版我按"首尾边就是替身点"
      猜，A2 直接量出 1.14 的假数（首边其实是自由段）。
    """
    from ui.map_view import build_line_points_ex, line_station_xy
    out = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        if len(seq) < 2:
            continue
        pts, ebl, _keys = build_line_points_ex(lid, seq, st, want_keys=True)
        offs = []
        for nm in seq:
            s = st.get(nm) or {}
            x, y = line_station_xy(s, lid)
            d = (s.get("lanes") or {}).get(lid)
            if d:
                try:
                    x, y = x + float(d[0]), y + float(d[1])
                except (TypeError, ValueError, IndexError):
                    pass
            offs.append((float(x), float(y)))
        # 按序定位每站走廊点在 pts 里的下标
        idxs = []
        pos = 0
        ok = True
        for o in offs:
            hit = None
            for k in range(pos, len(pts)):
                if (abs(pts[k].x() - o[0]) < 0.51
                        and abs(pts[k].y() - o[1]) < 0.51):
                    hit = k
                    break
            if hit is None:
                ok = False
                break
            idxs.append(hit)
            pos = hit
        if not ok:
            continue
        for i in range(1, len(seq)):
            i0, i1 = idxs[i - 1], idxs[i]
            if i1 <= i0:
                continue
            mid = [pts[k] for k in range(i0, i1 + 1)]
            # 边 k（mid[k]→mid[k+1]）的 ebl = ebl[i0 + k + 1]
            ebs = [ebl[i0 + k + 1] if (i0 + k + 1) < len(ebl) else ""
                   for k in range(len(mid) - 1)]
            d = math.hypot(offs[i][0] - offs[i - 1][0],
                           offs[i][1] - offs[i - 1][1])
            ta = len((st.get(seq[i - 1]) or {}).get("lines") or []) > 1
            tb = len((st.get(seq[i]) or {}).get("lines") or []) > 1
            out.append((lid, seq[i - 1], seq[i], mid, ebs, d, ta and tb))
    return out


def metrics(segs, only_both=True):
    """最坏情况统计。only_both=True 只看「相邻两站都是换乘站」的段
    —— 那正是用户报告的场景（v2.6.56 之前的 29 段覆盖比 0.90~0.94）。"""
    worst_turn = 0.0          # 短边上的最大转角
    worst_turn_where = None
    worst_gap = 1e9           # 相邻两个显著折点之间的最小距离
    worst_gap_where = None
    n_short_bad = 0
    n_gap_bad = 0
    n = 0
    for lid, a, b, mid, ebs, d, both in segs:
        if only_both and not both:
            continue
        if len(mid) < 3:
            continue
        n += 1
        edge_len, edge_ang = [], []
        for k in range(len(mid) - 1):
            dx = mid[k + 1].x() - mid[k].x()
            dy = mid[k + 1].y() - mid[k].y()
            L = math.hypot(dx, dy)
            edge_len.append(L)
            edge_ang.append(math.degrees(math.atan2(dy, dx)))
        # 每个内部顶点 k（mid[k]）的转角
        turns = []
        for k in range(1, len(edge_len)):
            ta = abs((edge_ang[k] - edge_ang[k - 1] + 180.0) % 360.0 - 180.0)
            sl = min(edge_len[k - 1], edge_len[k])
            if sl < SHORT and ta > worst_turn:
                worst_turn = ta
                worst_turn_where = "%s %s→%s (边%.1fpx)" % (lid, a, b, sl)
            if sl < SHORT and ta > MAXTURN:
                n_short_bad += 1
            if ta > TURN_MIN:
                turns.append(k)
        # A1：相邻两个显著折点挨得太近
        for x, y in zip(turns, turns[1:]):
            gap = sum(edge_len[x:y])         # 顶点 x 到顶点 y 之间的边长和
            if gap < worst_gap:
                worst_gap = gap
                worst_gap_where = ("%s %s→%s (两个折点只隔 %.1fpx，转角 %.0f°/%.0f°)"
                                   % (lid, a, b, gap,
                                      _turn_at(edge_ang, x), _turn_at(edge_ang, y)))
            if gap < GAP_MIN:
                n_gap_bad += 1
    return dict(worst_turn=worst_turn, worst_turn_where=worst_turn_where,
                worst_gap=worst_gap if worst_gap < 1e9 else 0.0,
                worst_gap_where=worst_gap_where,
                n_short_bad=n_short_bad, n_gap_bad=n_gap_bad, n=n)


def _turn_at(edge_ang, k):
    return abs((edge_ang[k] - edge_ang[k - 1] + 180.0) % 360.0 - 180.0)


def probe():
    """子进程模式：只算指标并打印，供变异自检对比"""
    app = QApplication.instance() or QApplication(sys.argv[:1])       # noqa: F821
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    segs = collect(st, lines)
    print("%s %s" % (METRIC_TAG, json.dumps(
        dict(both=metrics(segs, True), all=metrics(segs, False)))))
    return 0


def main():
    if "--probe" in sys.argv:
        return probe()
    app = QApplication.instance() or QApplication(sys.argv[:1])       # noqa: F841
    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    segs = collect(st, lines)
    mb = metrics(segs, True)      # 「两站都是换乘站」
    ma = metrics(segs, False)     # 全部段（宽松）

    ok = 0
    bad = 0
    print("「相邻两站都是换乘站」的段 %d 个（用户报告的场景）；全部段 %d 个"
          % (mb["n"], ma["n"]))
    print("-" * 66)

    def chk(name, cond, detail):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  [OK]   %s\n         %s" % (name, detail))
        else:
            bad += 1
            print("  [FAIL] %s\n         %s" % (name, detail))

    chk("A1 两站都换乘：两个折点扎堆",
        mb["n_gap_bad"] == 0,
        "相邻显著折点(>%.0f°)只隔 %.1fpx（限 %.0fpx），违规 %d 处  %s"
        % (TURN_MIN, mb["worst_gap"], GAP_MIN, mb["n_gap_bad"],
           mb["worst_gap_where"]))
    chk("A2 两站都换乘：短边上的急折",
        mb["n_short_bad"] == 0,
        "短边(%.0fpx)+急折(>%.0f°) 共 %d 处，最大转角 %.1f°  %s"
        % (SHORT, MAXTURN, mb["n_short_bad"], mb["worst_turn"],
           mb["worst_turn_where"]))

    # ---- C 组：全部段只报数（宽松，允许 90° 直角进站造成的短边） ----
    print("  [INFO] 全部段：折点扎堆 %d 处（最近 %.1fpx，%s）；"
          % (ma["n_gap_bad"], ma["worst_gap"], ma["worst_gap_where"]))
    print("         短边急折 %d 处（最大转角 %.1f°，%s）"
          % (ma["n_short_bad"], ma["worst_turn"], ma["worst_turn_where"]))

    # ---- B 组：变异自检 ----
    print("-" * 66)
    env = dict(os.environ)
    env["METROEDITOR_STUB_FRAC"] = "1.0"
    r = subprocess.run([PY, str(Path(__file__).resolve()), "--probe"],
                       capture_output=True, text=True, env=env, cwd=str(SRC))
    m2 = None
    for line in (r.stdout or "").splitlines():
        if METRIC_TAG in line:
            m2 = json.loads(line.split(METRIC_TAG, 1)[1].strip())
    if m2 is None:
        chk("B 变异自检（STUB_FRAC=1.0）", False,
            "子进程没给出指标：%s" % ((r.stderr or "")[-300:]))
    else:
        b2 = m2["both"]
        print("  变异 STUB_FRAC=1.0（退回 v2.6.55 各算各的）：折点扎堆 %d 处、"
              "最近 %.1fpx、短边急折 %d 处"
              % (b2["n_gap_bad"], b2["worst_gap"], b2["n_short_bad"]))
        chk("B1 变异必须让 A1 失败", b2["n_gap_bad"] > 0,
            "变异后折点扎堆 %d 处（>0 才对）  %s"
            % (b2["n_gap_bad"], b2["worst_gap_where"]))
        chk("B2 变异必须让全局也变差",
            b2["worst_gap"] < mb["worst_gap"] - 1.0,
            "变异最近间距 %.1fpx vs 现状 %.1fpx"
            % (b2["worst_gap"], mb["worst_gap"]))
    print("-" * 66)
    print("通过 %d / 失败 %d" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication                        # noqa: E402
    sys.exit(main())
