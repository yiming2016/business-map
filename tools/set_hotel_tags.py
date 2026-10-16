# -*- coding: utf-8 -*-
"""v2.6.70：按酒店分级清单给站点追加 hotel_* 标签（最高级酒店名）。

映射（与商场一致的 红/金/紫/绿 = 一/二/三/四级）：
  S级→hotel_red  A级→hotel_gold  B级→hotel_purple  C级→hotel_green
一站有多家酒店 → 只加**最高级**那一家的名字（图标也取该级）。
已有 tags（商场等）的站追加在后面。幂等：已有 hotel 组的站只更新文字/级别。
"""
import json
import re
import shutil
import time
from pathlib import Path

TXT = Path(r"C:/Users/29773/Pictures/酒店/新建 文本文档.txt")
DATA = Path(r"C:/software/subway/软件/data/stations.json")

TIER_RANK = {"S": 1, "A": 2, "B": 3, "C": 4}
TIER_ICON = {"S": "hotel_red", "A": "hotel_gold", "B": "hotel_purple", "C": "hotel_green"}

def parse_hotels():
    out = {}
    for m in re.finditer(r"-\s*(\S+?)站：(.+)", TXT.read_text(encoding="utf-8")):
        name, body = m.group(1), m.group(2)
        items = []
        for part in re.split(r"[、，]", body):
            mm = re.match(r"【([SABC])级】(.+)", part.strip())
            if mm:
                items.append((mm.group(1), mm.group(2).strip()))
        if items:
            out[name] = items
    return out

def main():
    hotels = parse_hotels()
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    stations = doc["stations"]

    def hotel_for(key):
        cands = {key, key[:-1] if key.endswith("站") else key,
                 key.replace("(T3)", "")}
        if "机场" in cands:
            cands.add("机场(T3)")
        for c in cands:
            if c in hotels:
                return hotels[c]
        return None

    backup = DATA.with_name(f"stations.json.bak_hotel_{time.strftime('%H%M%S')}")
    shutil.copy2(DATA, backup)
    print(f"备份 -> {backup.name}")

    applied, missing = [], []
    for key, st in stations.items():
        entry = hotel_for(key)
        if entry is None:
            continue
        if key not in {k for k in stations if hotel_for(k)}:
            missing.append(key)
            continue
        best = min((t for t, _ in entry), key=lambda x: TIER_RANK[x])
        name = re.sub(r"【[^】]*】\s*$", "",
                      next(nm for t, nm in entry if t == best)).strip()
        tags = list(st.get("tags") or [])
        for t in tags:
            if str(t.get("icon", "")).startswith("hotel_"):
                t["icon"] = TIER_ICON[best]
                t["text"] = name
                break
        else:
            tags.append({"icon": TIER_ICON[best], "text": name, "pos": "left"})
        st["tags"] = tags
        applied.append((key, best, name))

    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    n_over = sum(1 for k, _s in stations.items()
                 if sum(1 for t in (_s.get("tags") or []) if str(t.get("icon", "")).startswith("hotel_")) > 1)
    print(f"已配酒店标签：{len(applied)} 站（重复 hotel 组的站数={n_over}）")
    for k, t, nm in sorted(applied, key=lambda x: {"S": 0, "A": 1, "B": 2, "C": 3}[x[1]]):
        print(f"  {k} = {t}级 {nm}")
    for k in ("后海", "深圳北站", "岗厦", "机场(T3)"):
        print(f"  {k}.tags = {json.dumps(stations[k].get('tags'), ensure_ascii=False)}")

if __name__ == "__main__":
    main()
