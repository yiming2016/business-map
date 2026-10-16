# -*- coding: utf-8 -*-
"""
core/train_consist.py
========================
各线路的**车厢编组**（强冷 / 弱冷 / 商务车厢）静态资料。

数据来源：用户提供的三张官方示意图（2026-09-24 收到，配色经像素采样确认）。
    · 图1：6 节编组 —— 1/6 弱冷，2-5 强冷
    · 图2：8 节编组 —— 1/8 弱冷，2-7 强冷
    · 图3：11 号线 —— 1/6 弱冷、2-5 强冷，且 **7/8 节为商务车厢**
      （原图是"普通车厢"和"商务车厢"两张图，这里按用户要求合成**一个**列车图标）

为什么放在 Python 里而不是 data/*.json：
    这是**固定参考资料**，不是用户会编辑的数据。放进 data/ 反而多一份
    "打包快照 vs 用户目录"的同步问题（新增文件在已安装的 软件/data 里可能不存在）。

★ 配色是像素采样来的，不是凭感觉调的；要改请连同截图一起改。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 车厢类型
WEAK = "w"        # 弱冷车厢
STRONG = "s"      # 强冷车厢
BIZ = "b"         # 商务车厢

CAR_NAME = {
    WEAK: "弱冷车厢",
    STRONG: "强冷车厢",
    BIZ: "商务车厢",
}

# 配色（从截图采样；fill=车身底、border=车身描边、accent=车内图标与强调）
PALETTE = {
    WEAK:   {"fill": "#E0EDFA", "border": "#9CCBEE", "accent": "#3FA9E2"},
    STRONG: {"fill": "#E0E3F5", "border": "#AEB8F1", "accent": "#7385EA"},
    BIZ:    {"fill": "#F4EEE4", "border": "#DFCFA6", "accent": "#C4A468"},
}

# 图例里"这节车厢属于哪一类"的文字模板
LEGEND_FMT = {
    WEAK: "%s节为弱冷车厢",
    STRONG: "%s节为强冷车厢",
    BIZ: "%s节车厢为商务车厢",     # 原图就是这么措辞的（多一个"车厢"）
}

# ---------------------------------------------------------------- 编组表
SIX = WEAK + STRONG * 4 + WEAK          # 1弱 2-5强 6弱
EIGHT = WEAK + STRONG * 6 + WEAK        # 1弱 2-7强 8弱
ELEVEN = WEAK + STRONG * 4 + WEAK + BIZ * 2   # 1弱 2-5强 6弱 7-8商务

CONSIST: Dict[str, str] = {
    # 图1：六节编组
    "1": SIX, "2": SIX, "3": SIX, "4": SIX, "5": SIX,
    "6": SIX, "7": SIX, "8": SIX, "9": SIX,
    "12": SIX, "16": SIX,
    # 图2：八节编组
    "10": EIGHT, "13": EIGHT, "14": EIGHT, "20": EIGHT,
    # 图3：十一号线（含商务车厢）
    "11": ELEVEN,
    # 未列入的（6号线支线 / 有轨电车 / 有轨电车支线 / 坪山云巴）——
    # 用户没给这几条的编组资料，consist_for() 返回 None，界面显示"暂无资料"。
}


def consist_for(line_id: str) -> Optional[str]:
    """取某条线路的编组字符串（如 "wssssw"）。没有资料返回 None。"""
    return CONSIST.get(line_id)


def car_count(consist: str) -> int:
    return len(consist)


def _fmt_positions(pos: List[int]) -> str:
    """
    把节号列表排版成人看的短串（跟官方图一致）：

        1,6      → "1/6"       （不连续 → 斜杠）
        2,3,4,5  → "2-5"       （连续且 ≥3 节 → 连字符）
        7,8      → "7/8"       （只连续 2 节，官方图用的也是斜杠）
    """
    pos = sorted(pos)
    if not pos:
        return ""
    runs: List[List[int]] = [[pos[0]]]
    for p in pos[1:]:
        if p == runs[-1][-1] + 1:
            runs[-1].append(p)
        else:
            runs.append([p])
    parts: List[str] = []
    for r in runs:
        if len(r) >= 3:
            parts.append("%d-%d" % (r[0], r[-1]))
        else:
            parts.extend(str(x) for x in r)
    return "/".join(parts)


def legend_items(consist: str) -> List[Tuple[str, str, str]]:
    """
    生成图例行：[(车厢类型, 节号串, 完整文字), ...]，按"首次出现的顺序"排。
        SIX    → [("w","1/6","1/6节为弱冷车厢"), ("s","2-5","2-5节为强冷车厢")]
        ELEVEN → […, ("b","7/8","7/8节车厢为商务车厢")]
    """
    order: List[str] = []
    for c in consist:
        if c not in order:
            order.append(c)
    out: List[Tuple[str, str, str]] = []
    for kind in order:
        pos = [i + 1 for i, c in enumerate(consist) if c == kind]
        txt_range = _fmt_positions(pos)
        out.append((kind, txt_range, LEGEND_FMT[kind] % txt_range))
    return out


def cars(consist: str) -> List[str]:
    """按节号顺序展开成 [类型, ...]。"""
    return list(consist)
