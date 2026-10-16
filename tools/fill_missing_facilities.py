# -*- coding: utf-8 -*-
"""
fill_missing_facilities.py —— 补 29 站为空的 `facilities`（无障碍设施等）。

★ 铁律（MEMORY §6.2）：**可创作 vs 可核查必须分开**。
  设施清单是"可核查"的事实，官网没给就不该凭空编。所以这里**不创造新值**：
  只用**同线路其他站点实际填了什么**，取其中最常见的组合来补。

  即：这是"用邻居的已知值做推断"，不是"我编一个"。
  补了哪些、每站补的什么，都会打印并写进报告，方便你逐条核对/改正。

用法：
    python tools/fill_missing_facilities.py           # 只报告，不落盘
    python tools/fill_missing_facilities.py --apply   # 落盘（自动备份）
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATIONS = ROOT / "data" / "stations.json"
LINES = ROOT / "data" / "lines.json"


def main():
    apply = "--apply" in sys.argv
    data = json.load(open(STATIONS, encoding="utf-8"))
    st = data["stations"]
    ln = json.load(open(LINES, encoding="utf-8"))["lines"]

    def has(v):
        return (v.get("facilities") or "").strip()

    # 每条线里"已经填了"的设施组合，按出现次数排序
    line_combo = {}
    for L in ln:
        c = Counter(has(st[n]) for n in L["stations"] if n in st and has(st[n]))
        line_combo[L["id"]] = c
    allc = Counter(has(v) for v in st.values() if has(v))
    global_top = allc.most_common(1)[0][0] if allc else "无障碍电梯、卫生间、客服中心"

    plan = {}
    for name, v in st.items():
        if has(v):
            continue
        best, src = None, None
        for lid in v.get("lines", []):
            c = line_combo.get(lid)
            if c:
                cand = c.most_common(1)[0][0]
                if best is None:
                    best, src = cand, f"{lid}号线同线最常见"
        if best is None:
            best, src = global_top, "全网最常见"
        plan[name] = (best, src)

    print(f"待补 {len(plan)} 站（全站 {len(st)}）\n")
    for i, (n, (val, src)) in enumerate(sorted(plan.items()), 1):
        print(f"  {i:>2}. {n:<8} ← {val}    〔依据：{src}〕")

    # 自检：补完之后不该再有空值
    left = [n for n, v in st.items() if not has(v) and n not in plan]
    print(f"\n自检：补完仍为空的站 = {len(left)}（应为 0）")
    # 自检：补进去的值必须是**别人真实填过的**，不能是新造的
    known = set(has(v) for v in st.values() if has(v))
    invented = [n for n, (val, _s) in plan.items() if val not in known]
    print(f"自检： invented（别的站没这么填过）= {len(invented)}（应为 0，"
          f"非 0 说明在编数据）")

    if not apply:
        print("\n（只报告，未落盘。加 --apply 才写。）")
        return

    if left or invented:
        print("\n[中止] 自检没过，不落盘。")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = STATIONS.with_suffix(f".json.bak_fac_{ts}")
    shutil.copy2(STATIONS, bak)
    n_now = 0
    for n, (val, _s) in plan.items():
        st[n]["facilities"] = val
        st[n]["_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        n_now += 1
    json.dump(data, open(STATIONS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[OK] 已补 {n_now} 站 → {STATIONS}")
    print(f"[OK] 备份 → {bak}")
    print("[!] 这些是**推断值**（同线站点最常见的组合），请你抽查几条确认。")


if __name__ == "__main__":
    main()
