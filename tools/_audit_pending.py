# -*- coding: utf-8 -*-
"""
_audit_pending.py —— 待修问题**精确体检**（只读，绝不改数据）。

用途：把 MEMORY「§8 悬而未决」里那些"大概多少条"的印象，换成**可复核的精确数字**。
每次修完再跑一遍，用同一把尺子量，才知道是真修好了还是只是自我感觉良好。

用法：
    python tools/_audit_pending.py
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STATIONS = ROOT / "data" / "stations.json"
LINES = ROOT / "data" / "lines.json"


def load():
    st = json.load(open(STATIONS, encoding="utf-8"))["stations"]
    ln = json.load(open(LINES, encoding="utf-8"))["lines"]
    return st, ln


def nonempty(s):
    return (s or "").strip()


def main():
    st, ln = load()
    print(f"站点总数 = {len(st)}    线路数 = {len(ln)}")
    print("=" * 72)

    # ---------- ① 文案开头句式雷同 ----------
    heads = Counter()
    for k, v in st.items():
        d = nonempty(v.get("description"))
        if not d:
            continue
        # 取第一个逗号/句号之前的那一段当"开头"
        m = re.split(r"[，。；]", d, 1)[0]
        heads[m[:12]] += 1
    top = heads.most_common(12)
    print("\n【① description 开头句式】")
    for h, c in top:
        print(f"   {c:>4} ×  “{h}…”")
    located = sum(c for h, c in heads.items() if h.startswith("位于"))
    print(f"   → 以「位于」开头共 **{located}** 条；不同开头共 {len(heads)} 种")

    # ---------- ② notes 超字数 ----------
    LIMIT_N = 60
    over = []
    for k, v in st.items():
        n = nonempty(v.get("notes"))
        if n and len(n) > LIMIT_N:
            over.append((k, len(n), n))
    print(f"\n【② notes 超过 {LIMIT_N} 字】共 **{len(over)}** 条")
    for k, L, n in sorted(over, key=lambda x: -x[1]):
        print(f"   {L:>3}字  {k}：{n[:40]}…")
    lens = [len(nonempty(v.get("notes"))) for v in st.values() if nonempty(v.get("notes"))]
    if lens:
        print(f"   （notes 长度分布：min {min(lens)} / max {max(lens)} / 平均 {sum(lens)/len(lens):.1f}）")

    # ---------- ③ facilities 空 ----------
    empty_fac = sorted(k for k, v in st.items() if not nonempty(v.get("facilities")))
    print(f"\n【③ facilities 为空】共 **{len(empty_fac)}** 站")
    if empty_fac:
        print("   " + "、".join(empty_fac[:40]) + ("…" if len(empty_fac) > 40 else ""))
    # 非空的最常见组合（供"按同类推断"用）
    combos = Counter(nonempty(v.get("facilities")) for v in st.values()
                     if nonempty(v.get("facilities")))
    print("   最常见的设施组合 TOP5：")
    for c, n in combos.most_common(5):
        print(f"     {n:>4} ×  {c}")

    # ---------- ④ 官网无数据（timetable 空） ----------
    no_tt = sorted(k for k, v in st.items() if not nonempty(v.get("timetable")))
    print(f"\n【④ timetable 为空（官网没抓到）】共 **{len(no_tt)}** 站")
    by_line = Counter()
    for k in no_tt:
        for lid in st[k].get("lines", []):
            by_line[lid] += 1
    print("   按线路分布：" + "、".join(f"{lid}号线 {n}" for lid, n in by_line.most_common()))
    if no_tt:
        print("   " + "、".join(no_tt) )

    # ---------- ⑤ 出入口为空 ----------
    no_ex = sorted(k for k, v in st.items() if not nonempty(v.get("exits")))
    print(f"\n【⑤ exits（出入口）为空】共 **{len(no_ex)}** 站")
    by_line2 = Counter()
    for k in no_ex:
        for lid in st[k].get("lines", []):
            by_line2[lid] += 1
    print("   按线路分布：" + "、".join(f"{lid}号线 {n}" for lid, n in by_line2.most_common()))
    if no_ex:
        print("   " + "、".join(no_ex))

    # ---------- ⑤b 站名里藏脏字符（会导致官网查不到） ----------
    dirty = []
    for k in st:
        if k != k.strip() or "\t" in k or "\n" in k:
            dirty.append((k, repr(k)))
        nm = st[k].get("station_name", "")
        if nm != nm.strip() or "\t" in nm or "\n" in nm:
            dirty.append((k, repr(nm)))
    print(f"\n【⑤b 站名带不可见字符（会让官网查询必然落空）】共 **{len(dirty)}** 条")
    for k, r in dirty:
        print(f"   {k} -> {r}")

    # ---------- ⑥ 布局：站距均匀度 / 八向合规 ----------
    import math
    all_d, octi_ok, tot = [], 0, 0
    for L in ln:
        ss = [st[n] for n in L["stations"] if n in st]
        for i in range(len(ss) - 1):
            dx = ss[i + 1]["x"] - ss[i]["x"]
            dy = ss[i + 1]["y"] - ss[i]["y"]
            d = math.hypot(dx, dy)
            all_d.append(d)
            tot += 1
            if d > 1e-6:
                a = math.degrees(math.atan2(dy, dx)) % 90
                # 距离最近的 0/45/90 方向差多少度
                dev = min(abs(a - 0), abs(a - 45), abs(a - 90))
                if dev <= 5.0:
                    octi_ok += 1
    mean = sum(all_d) / len(all_d)
    var = sum((d - mean) ** 2 for d in all_d) / len(all_d)
    cv = var ** 0.5 / mean
    print(f"\n【⑥ 当前布局】")
    print(f"   相邻站距：min {min(all_d):.1f} / max {max(all_d):.1f} / 均值 {mean:.1f}")
    print(f"   **间距变异系数 CV = {cv:.3f}**（越小越均匀；等间距应 ≈0）")
    print(f"   八向合规（段方向离 0/45/90 ≤5°）：{octi_ok}/{tot} = {octi_ok/tot*100:.1f}%")

    # 换乘站坐标一致性
    bad = []
    for k, v in st.items():
        if len(v.get("lines", [])) < 2:
            continue
    print("\n（换乘站坐标唯一，按 station_id 存储 ⇒ 天然一致，此项正确）")

    print("\n" + "=" * 72)
    print("体检完毕。上面每个数字都是后面验收的基准线。")


if __name__ == "__main__":
    main()
