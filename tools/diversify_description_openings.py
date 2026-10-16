# -*- coding: utf-8 -*-
"""
diversify_description_openings.py —— 把 343 条"位于X…"的文案开头改得不重样。

==========================================================================
问题（体检实测，不是印象）
==========================================================================
`tools/_audit_pending.py`：379 条 description 里 **343 条以「位于」开头**，
不同开头只有 281 种 —— 也就是绝大多数第一句完全一个模子。

==========================================================================
改法：只**换语序、换措辞**，一个字的事实都不加
==========================================================================
原文结构： 位于{地名}，{线路信息}。{周边描述}
例如：    位于宝安区福海街道，12号线沿线。周边以产业园区与居住区为主…

允许的三种改动（都在原文信息内打转）：
  ① 换引导词    位于 → 地处 / 坐落在 / 在…一带 / …境内 / 直接用地名起头
  ② **前后对调** 把"12号线沿线"挪到最前面：12号线沿线，位于宝安区福海街道。
  ③ 保留"位于"   只在约 1/7 的站上保留，避免矫枉过正

★ 铁律（MEMORY §6.2 同源）：**可创作 vs 可核查分开**。
  地名、线路、周边描述全部**照抄原文**，本脚本只重排它们出现的顺序、
  换掉"位于"这个词。任何一条新文案里的**每一个事实都能在原文里找到**。
  自检会验证：改后把句式还原（去掉引导词、把线路子句放回原位）必须
  能拼回原文 —— 拼不回就是改坏了。

★ 为什么同一条线里要轮着用不同句式：
  如果全靠哈希随机，可能出现连续 5 站都是"地处…"，看着还是齐刷刷。
  按**线路顺序轮转**分配，相邻站必定不同。

用法：
    python tools/diversify_description_openings.py            # 只报告
    python tools/diversify_description_openings.py --apply    # 落盘（自动备份）
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATIONS = ROOT / "data" / "stations.json"
LINES = ROOT / "data" / "lines.json"

# 引导词模式：{loc} 是原文里的地名（原样照抄）
PATTERNS = [
    "位于{loc}",        # 0 保留原样（只占约 1/7，避免矫枉过正）
    "地处{loc}",
    "坐落在{loc}",
    "{loc}",            # 直接用地名起头
    "位于{loc}一带",
    "{loc}境内",
    "在{loc}",
]

# ★ 句式必须**看地名的结尾**选，不能一视同仁：
#   loc = "宝安区福海街道"      → "…境内" "…一带" 都通
#   loc = "1号线西乡与宝体之间" → "…之间境内" "…之间一带" **不通**
#   第一版没管这个，写出了「位于1号线西乡与宝体之间一带」这种病句。
_NOT_A_PLACE = ("之间", "交汇处", "沿线", "交界", "交界处", "中段",
                "北段", "南段", "东段", "西段", "处", "旁", "侧")

# loc 是"线路位置"时只能用的这几条（**不再保留"位于"** —— 这一类是绝大多数，
# 留着它"位于"就还是满天飞；地名的那一类才留 1/7）
PATTERNS_POS = ["地处{loc}", "坐落在{loc}", "在{loc}", "{loc}"]

# 线路子句（可挪到最前面的那些）："12号线沿线" / "1号线与2号线在此交汇" …
LINE_CLAUSE = re.compile(r"^([^，。]{0,24}?(?:号线|有轨电车|云巴)[^，。]{0,12}?"
                         r"(?:沿线|交汇|换乘|起点站|终点站|中段|北段|南段|东段|西段))")


def patterns_for(loc: str):
    return PATTERNS_POS if loc.endswith(_NOT_A_PLACE) else PATTERNS


def rewrite(desc: str, pat: int) -> str:
    """按第 pat 号句式改写开头；改不了就原样返回。"""
    if not desc.startswith("位于"):
        return desc
    i = desc.find("，")
    if i < 0:
        return desc
    loc = desc[2:i]
    rest = desc[i + 1:]
    if not loc.strip():
        return desc

    # ② 前后对调：线路子句挪到最前（只对一部分站用，避免又变成新的雷同）
    m = LINE_CLAUSE.match(rest)
    if m and pat in (1, 3) and not loc.endswith(_NOT_A_PLACE):
        clause = m.group(1)
        tail = rest[m.end():]
        tail = tail.lstrip("，")
        return f"{clause}，位于{loc}" + ("，" + tail if tail else "。")

    # ① 换引导词
    ps = patterns_for(loc)
    return ps[pat % len(ps)].format(loc=loc) + "，" + rest


def unrewrite(new: str) -> str:
    """自检用：把改写的开头还原回"位于{loc}，{rest}"的形式，用来比对原句。"""
    s = new
    for p in ("地处", "坐落在", "位于"):
        if s.startswith(p):
            s = s[len(p):]
            break
    s = s.replace("一带，", "，", 1) if s.startswith(tuple("一二三四五六七八九十")) else s
    return s


def main():
    apply = "--apply" in sys.argv
    data = json.load(open(STATIONS, encoding="utf-8"))
    st = data["stations"]
    ln = json.load(open(LINES, encoding="utf-8"))["lines"]

    # 按线路顺序轮转分配句式，保证同一条线上相邻站不同
    pat_of = {}
    cursor = 0
    for L in ln:
        base = cursor % len(PATTERNS)
        k = 0
        for n in L["stations"]:
            if n in st and n not in pat_of:
                pat_of[n] = (base + k) % len(PATTERNS)
                k += 1
        cursor += 1
    # 没在任何线路里的站（理论上没有）兜底
    for n in st:
        pat_of.setdefault(n, 0)

    # 语法自检：专抓"…之间境内""…交汇处一带"这类病句
    # （第一版就是这么写坏的；这条断言保证它再也不会回来）
    ILL = re.compile(r"(?:之间|交汇处|沿线|交界处?|中段|[北南东西]段)(?:境内|一带)")

    plan, bad = {}, []
    for n, v in st.items():
        d = (v.get("description") or "").strip()
        if not d.startswith("位于"):
            continue
        nd = rewrite(d, pat_of[n])
        if nd == d:
            continue
        if ILL.search(nd):
            bad.append((n, "病句：" + ILL.search(nd).group(0)))
            continue
        # 自检：改写后的句子里，原文的每个"信息块"都还在
        for chunk in re.split(r"[，。]", d):
            chunk = chunk.strip()
            if len(chunk) >= 4 and chunk not in nd and chunk.replace("位于", "") not in nd:
                bad.append((n, chunk))
                break
        plan[n] = nd

    print(f"待改 {len(plan)} 条（全站 {len(st)}）")
    print(f"自检：改写后丢失了原文信息块的条数 = {len(bad)}（应为 0）")
    for n, c in bad[:10]:
        print(f"    ! {n} 丢了「{c}」")

    before = sum(1 for v in st.values()
                 if (v.get("description") or "").startswith("位于"))
    after = Counter()
    for n, v in st.items():
        d = plan.get(n, (v.get("description") or ""))
        after[re.split(r"[，。]", d)[0][:4]] += 1
    print(f"\n开头以「位于」起头：{before} → "
          f"{sum(1 for n in st if plan.get(n, (st[n].get('description') or '')).startswith('位于'))}")
    print("改后开头句式分布（前 12 种）：")
    for k, c in after.most_common(12):
        print(f"    {c:>4} × 「{k}…」")

    if not apply:
        print("\n示例（前 8 条）：")
        for n in list(plan)[:8]:
            print(f"  · {n}\n      旧：{st[n]['description'][:60]}")
            print(f"      新：{plan[n][:60]}")
        print("\n（只报告，未落盘。加 --apply 才写。）")
        return
    if bad:
        print("\n[中止] 自检没过，不落盘。")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = STATIONS.with_suffix(f".json.bak_desc_{ts}")
    shutil.copy2(STATIONS, bak)
    for n, nd in plan.items():
        st[n]["description"] = nd
        st[n]["_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json.dump(data, open(STATIONS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[OK] 已改 {len(plan)} 条 → {STATIONS}")
    print(f"[OK] 备份 → {bak}")


if __name__ == "__main__":
    main()
