# -*- coding: utf-8 -*-
"""v2.6.68：按用户商场分级清单，给站点自动配「最高级」商场图标。

数据源：C:/Users/29773/Pictures/新建 文本文档 (2).txt
  格式：- 岗厦站：【A级】One Avenue卓悦中心、【C级】连城新天地【地下直达】

映射（用户此前定的红/金/紫/绿 = 一/二/三/四级）：
  S级→mall_red(红·一级)  A级→mall_gold(金·二级)  B级→mall_purple(紫·三级)  C级→mall_green(绿·四级)

规则：
  · 一站有多个商场 → 只取**最高级**（S>A>B>C）。
  · 已有 hsr/airport 图标的站**不覆盖**（如深圳北站）。
"""
import json
import re
import shutil
import time
from pathlib import Path

TXT = Path(r"C:/Users/29773/Pictures/新建 文本文档 (2).txt")
DATA = Path(r"C:/software/subway/软件/data/stations.json")

TIER_RANK = {"S": 1, "A": 2, "B": 3, "C": 4}
TIER_ICON = {"S": "mall_red", "A": "mall_gold", "B": "mall_purple", "C": "mall_green"}
TIER_NAME = {"S": "S级", "A": "A级", "B": "B级", "C": "C级"}

def main():
    text = TXT.read_text(encoding="utf-8")
    entries = {}   # 站名 -> (rank, tier, malls)
    for m in re.finditer(r"-\s*(\S+?)站：(.+)", text):
        name, body = m.group(1), m.group(2)
        tiers = re.findall(r"【([SABC])级】", body)
        if not tiers:
            continue    # “周边以社区商业为主”这类行
        best = min(tiers, key=lambda t: TIER_RANK[t])
        entries[name] = (TIER_RANK[best], best, len(tiers))
    print(f"清单里有商场的站：{len(entries)}")

    backup = DATA.with_name(f"stations.json.bak_mall_{time.strftime('%H%M%S')}")
    shutil.copy2(DATA, backup)
    print(f"备份 -> {backup.name}")

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    stations = doc["stations"]

    def find_key(name):
        if name in stations:
            return name
        if (name + "站") in stations:      # 深圳北站 这类本名带“站”
            return name + "站"
        return None

    applied, kept, missing = [], [], []
    for name, (rank, tier, n) in sorted(entries.items(), key=lambda kv: kv[1][0]):
        key = find_key(name)
        if key is None:
            missing.append(name)
            continue
        cur = str(stations[key].get("icon") or "")
        if cur and not cur.startswith("mall_"):
            kept.append((key, cur, TIER_NAME[tier]))
            continue
        stations[key]["icon"] = TIER_ICON[tier]
        applied.append((key, TIER_NAME[tier]))

    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已配商场图标：{len(applied)} 站")
    for k, t in applied:
        print(f"  {k} = {t}")
    print(f"已有高铁/机场图标不覆盖：{len(kept)} -> {[(k, c, t) for k, c, t in kept]}")
    print(f"清单有但库里没有：{len(missing)} -> {missing}")

if __name__ == "__main__":
    main()
