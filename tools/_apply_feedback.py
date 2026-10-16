# -*- coding: utf-8 -*-
"""把用户看图反馈的修正写进 logs/_final_coords.json（仍然不动业务数据）。

来源：用户 2026-09-30 对《复核_分区1..4》的口头反馈
  分区1：国展南应显示 20号线(青) ；深圳北 红点往左下
  分区2：布吉 蓝点往左上      ；14号线黄圈是 嶂背、坪山广场（→ 确认，标 ok）
  分区3：靠左(赤湾)圈的不是站 ；靠中(深圳湾公园/后海)描述存疑 ；靠右(福田口岸)有 4号线和 10号线两个
  分区4：黄木岗 往左下        ；红岭南 = 11号线那个点 ；湖贝 = 8号线那个点
"""
import json

SRC = "C:/software/subway/源码"
F = json.load(open(SRC + "/logs/_final_coords.json", encoding="utf-8"))
final, tag = F["final"], F["tag"]

# --- 绝对坐标覆盖（用户点名确认 / 用站名文字+走廊交点算出）---
ABSOLUTE = {
    "红岭南": (4398, 5499),     # 用户：11号线那个点（另有一个 9号线的在 (4502,5499)）
    "湖贝": (5015, 5124),       # 用户：8号线那个点（实测该点贴 2/8 走廊）
    "嶂背": (5983, 3113),       # 用户确认是 14号线
    "坪山广场": (6959, 2856),   # 用户确认是 14号线
    "国展南": (440, 2300),      # 位置不动，只改线属（见下）
    # ↓ 第 2 轮反馈（分区3 从左到右）
    "后海": (1740, 5924),       # 用户：往下那个 75×24 宽药丸，贴 2/8/11/13
    "深圳湾公园": (2616, 5874), # 用户确认
    "福田口岸": (3520, 5949),   # 用户确认是 4号线那个（10号线那个在 (3609,5949)）
    "赤湾": (832, 6506),        # 用户：在右上方（原图白圆点被竖排站名盖住，取 2/5 走廊交点）
}
# --- 按用户给的方向挪 ---
NUDGE = {
    "深圳北": (-32, +22),       # 用户：往左下
    "布吉": (-28, -22),         # 用户：往左上
    "黄木岗": (-24, +24),       # 用户：往左下
}

for nm, p in ABSOLUTE.items():
    final[nm] = list(p); tag[nm] = "ok"
for nm, (dx, dy) in NUDGE.items():
    p = final[nm]
    final[nm] = [p[0] + dx, p[1] + dy]
    tag[nm] = "moved"

# --- 线属修正（影响显示颜色）---
LINES_FIX = {
    "国展南": ["20"],           # 用户：是 20号线，不是 12号线
}
json.dump(LINES_FIX, open(SRC + "/logs/_lines_fix.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# --- 程序认不出来、留给用户在软件里拖的站 ---
UNCERTAIN = ["赤湾"]      # 只剩这一个：原图白圆点被站名文字盖住，取走廊交点，仍需目视
for nm in UNCERTAIN:
    tag[nm] = "unknown"

json.dump({"final": final, "tag": tag}, open(SRC + "/logs/_final_coords.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
from collections import Counter
print("标签统计:", dict(Counter(tag.values())))
print("留给用户在软件里拖的:", "、".join(UNCERTAIN))
print("线属修正:", LINES_FIX)
