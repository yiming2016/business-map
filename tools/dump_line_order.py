# -*- coding: utf-8 -*-
"""输出文字版全线路站序表（供人工核对）。产物：logs/线路站序_复刻版.md"""
import json

SRC = "C:/software/subway/源码"
ST = json.load(open(SRC + "/data/stations.json", encoding="utf-8"))["stations"]
LJ = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = LJ["lines"] if isinstance(LJ, dict) and "lines" in LJ else LJ
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
NAME = {str(l.get("id") or l.get("line_id")): l.get("name") for l in _l}
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _l}

out = ["# 全线路站序（按原图复刻版 · %d 站 / %d 线）" % (len(ST), len(_l)), "",
       "换乘站用【】标出，普通站用［］。**这一版是照原图重取的坐标，请你逐条核对站序和换乘。**", ""]


def mark(nm):
    s = ST.get(nm)
    if not s:
        return f"{nm}(缺)"
    return f"【{nm}】" if len(s["lines"]) > 1 else f"［{nm}］"


total = 0
for lid, seq in ORDER.items():
    if not seq:
        continue
    total += len(seq)
    out.append(f"## {NAME.get(lid, lid)}（{lid} · {COLOR.get(lid,'')}）{len(seq)} 站")
    out.append("")
    out.append("　".join(f"{i}.{mark(nm)}" for i, nm in enumerate(seq, 1)))
    out.append("")
    transfers = [n for n in seq if n in ST and len(ST[n]["lines"]) > 1]
    if transfers:
        out.append("换乘：" + "、".join(f"{n}({'/'.join(ST[n]['lines'])})" for n in transfers))
        out.append("")

out.insert(3, f"合计 {total} 个站次。")
open(SRC + "/logs/线路站序_复刻版.md", "w", encoding="utf-8").write("\n".join(out))
print("已写出 logs/线路站序_复刻版.md，共", total, "个站次")
