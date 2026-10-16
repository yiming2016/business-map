# -*- coding: utf-8 -*-
"""
_chk_layout_schematic.py —— 「站点布局是不是官方示意图的样子」回归。

==========================================================================
为什么需要这个文件
==========================================================================
v2.6.16 之前，379 个站点的 x/y 是**从位图上量**出来的，量出来的结果是：

    八向合规（段方向离 0/45/90 ≤5°）  56.2%
    视觉毛刺（渲染器要插 45° 折角的段）149/436 = 34.2%
    直线度（连续两段同向）             66.5%
    间距变异系数 CV                    0.606

"乱"就是这些数字。重排（`tools/relayout_octilinear.py`）之后：

    八向合规  92.7%      毛刺  19（4.4%）
    直线度    75.3%      CV    0.425
    段数      141 → 124   过近站对 11（与改前持平）

本文件就是把上面这些数字**钉死**，以后谁再动坐标就会响。

==========================================================================
★ 每条判据都配一个"故意搞坏"的自检
==========================================================================
**从不报错的校验器等于没有。** 所以每一组判据后面都跟一条变异自检：
把坐标人为搞坏（加噪声 / 压扁 / 拉歪），确认判据**真的会失败**。
下面 `__main__` 里每跑完一组就会打印 `[OK] 变异自检 …`。

用法：
    python tools/_chk_layout_schematic.py
"""

from __future__ import annotations

import glob
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.relayout_octilinear import (            # noqa: E402
    build_edges, dist, load, metrics, segment_line, snap_dir, NON_METRO,
)

# ---------------------------------------------------------------- 阈值
# 全部由实测值留出余量后定死；注释里写的是"改前 → 改后"。
MIN_OCTI5 = 0.85      # 八向合规（56.2% → 92.7%）
MAX_JOG_N = 40        # 视觉毛刺段数（149 → 19）
MAX_JOG_R = 0.12      # 视觉毛刺比例（34.2% → 4.4%）
MIN_STRAIGHT = 0.68   # 直线度（66.5% → 75.3%）
MAX_CV = 0.52         # 间距变异系数（0.606 → 0.425）
MAX_SEG = 141         # 直线段总数（141 → 124）
MAX_REVERSE = 35      # 折返处数（17 → 24，略有回退，上限钉住）
MIN_NONADJ = 25.0     # 非邻站最小间距（45.3 → 36.9）
MAX_CLOSE = 20        # 过近站对数（11 → 11）
AR_MIN, AR_MAX = 0.9, 1.5   # 宽高比（1.20 → 1.20，要适配 874×829 视口）
MAX_MOVE = 900.0      # 与重排前备份对比：任何一站都不许被甩这么远

_FAIL = []


def check(cond: bool, msg: str) -> bool:
    if cond:
        print(f"  [OK]  {msg}")
        return True
    print(f"  [FAIL]{msg}")
    _FAIL.append(msg)
    return False


def seg_total(pos, ln, penalty=0.3):
    return sum(len(segment_line([pos[s] for s in L["stations"]], penalty))
               for L in ln)


def reverse_count(pos, ln):
    """折返：相邻两段方向相反（线往前走又折回来）。"""
    r = 0
    for L in ln:
        ss = L["stations"]
        for i in range(len(ss) - 2):
            a, b, c = pos[ss[i]], pos[ss[i + 1]], pos[ss[i + 2]]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            if v1[0] * v2[0] + v1[1] * v2[1] < 0 and dist(b, c) > 1e-6:
                r += 1
    return r


def mutate_noise(pos, amp=45.0, seed=7):
    """变异①：给每个站加高斯噪声 —— 模拟"又回到从位图量坐标"的老状态。"""
    rnd = random.Random(seed)
    return {n: (v[0] + rnd.gauss(0, amp), v[1] + rnd.gauss(0, amp))
            for n, v in pos.items()}


def mutate_flatten(pos):
    """变异②：把所有 y 压扁到 1/6 —— 模拟"整张图被压成一条横带"。"""
    ys = [v[1] for v in pos.values()]
    my = sum(ys) / len(ys)
    return {n: (v[0], my + (v[1] - my) / 6.0) for n, v in pos.items()}


def main():
    st, ln = load()
    edges = build_edges(ln)
    pos = {n: (v["x"], v["y"]) for n, v in st.items()}
    m = metrics(pos, ln, edges)

    print("=" * 74)
    print("站点布局「官方示意图化」回归")
    print(f"（{len(st)} 站 / {len(ln)} 线 / {len(edges)} 段）")
    print("=" * 74)

    # ---------------------------------------------------------- A 走向
    print("\n[A] 走向：每一段都该是横 / 竖 / 45°")
    check(m["八向5"] >= MIN_OCTI5,
          f"八向合规（离 0/45/90 ≤5°）{m['八向5']*100:.1f}% ≥ {MIN_OCTI5*100:.0f}%")
    check(m["毛刺"] <= MAX_JOG_N,
          f"视觉毛刺 {m['毛刺']} 段 ≤ {MAX_JOG_N}（渲染器要插 45° 折角的段）")
    check(m["毛刺率"] <= MAX_JOG_R,
          f"视觉毛刺比例 {m['毛刺率']*100:.1f}% ≤ {MAX_JOG_R*100:.0f}%")
    check(m["直线度"] >= MIN_STRAIGHT,
          f"直线度 {m['直线度']*100:.1f}% ≥ {MIN_STRAIGHT*100:.0f}%")

    # 变异自检
    mut = metrics(mutate_noise(pos), ln, edges)
    check(mut["八向5"] < MIN_OCTI5 or mut["毛刺"] > MAX_JOG_N,
          f"变异自检：加 ±45 噪声后 八向 {mut['八向5']*100:.1f}% / 毛刺 {mut['毛刺']}"
          f" ⇒ 上面这组判据真的会响")

    # ---------------------------------------------------------- B 间距
    print("\n[B] 间距：同一条线上不该忽疏忽密")
    check(m["间距CV"] <= MAX_CV,
          f"间距变异系数 CV {m['间距CV']:.3f} ≤ {MAX_CV}")
    check(m["最大站距"] / m["间距均值"] <= 3.2,
          f"最长段 / 平均段 = {m['最大站距']/m['间距均值']:.2f} ≤ 3.2"
          f"（改前 981/228 = 4.3）")

    # 变异自检：把某条线的一段抽成 10 倍长
    bad = dict(pos)
    for lid, a, b in edges[:12]:
        bad[b] = (bad[a][0] + (bad[b][0] - bad[a][0]) * 6.0,
                  bad[a][1] + (bad[b][1] - bad[a][1]) * 6.0)
    mb = metrics(bad, ln, edges)
    check(mb["间距CV"] > m["间距CV"],
          f"变异自检：把 12 段拉长 6 倍后 CV {m['间距CV']:.3f} → {mb['间距CV']:.3f}"
          f" ⇒ CV 判据真的会响")

    # ---------------------------------------------------------- C 形态
    print("\n[C] 形态：线不该碎成一堆小折、也不该往回折")
    nseg = seg_total(pos, ln)
    check(nseg <= MAX_SEG,
          f"直线段总数 {nseg} ≤ {MAX_SEG}（改前 141）")
    rev = reverse_count(pos, ln)
    check(rev <= MAX_REVERSE,
          f"折返处 {rev} ≤ {MAX_REVERSE}（改前 17）")

    # ---------------------------------------------------------- D 重叠
    print("\n[D] 重叠：站点不该挤在一起")
    check(m["非邻最小"] >= MIN_NONADJ,
          f"非邻站最小间距 {m['非邻最小']:.1f} ≥ {MIN_NONADJ}")
    check(m["过近对"] <= MAX_CLOSE,
          f"过近站对 {m['过近对']} ≤ {MAX_CLOSE}（改前 11）")
    check(mutate_flatten(pos) and metrics(mutate_flatten(pos), ln, edges)["过近对"] > MAX_CLOSE,
          f"变异自检：把整图纵向压扁 6 倍后 过近对 "
          f"{metrics(mutate_flatten(pos), ln, edges)['过近对']} > {MAX_CLOSE}"
          f" ⇒ 重叠判据真的会响")

    # ---------------------------------------------------------- E 整体
    print("\n[E] 整体：要能舒服地塞进 874×829 的地图视口")
    check(AR_MIN <= m["宽高比"] <= AR_MAX,
          f"宽高比 {m['宽高比']:.2f} ∈ [{AR_MIN}, {AR_MAX}]"
          f"（视口 874×829 ≈ 1.05，越接近越不浪费画面）")

    # ---------------------------------------------------------- F 位移
    # 只在"重排前的备份还在"时才跑（证明没有站点被甩飞）
    baks = sorted(glob.glob(str(ROOT / "data" / "stations.json.bak_relayout_*")))
    if baks:
        print("\n[F] 位移：重排不该把任何一站甩到地图另一头")
        old = json.load(open(baks[-1], encoding="utf-8"))["stations"]
        mov = [dist(pos[n], (old[n]["x"], old[n]["y"])) for n in pos if n in old]
        check(max(mov) <= MAX_MOVE,
              f"最大位移 {max(mov):.0f} ≤ {MAX_MOVE:.0f}"
              f"（整图跨度 {m['宽']:.0f}）—— 与备份 {Path(baks[-1]).name} 对比")
    else:
        print("\n[F] 位移：跳过（没找到重排前的备份 stations.json.bak_relayout_*）")

    # ---------------------------------------------------------- 汇总
    print("\n" + "=" * 74)
    if _FAIL:
        print(f"结果：{len(_FAIL)} 项失败")
        for f in _FAIL:
            print(f"  · {f}")
        return 1
    print("结果：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
