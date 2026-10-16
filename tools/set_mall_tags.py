# -*- coding: utf-8 -*-
"""v2.6.69：把单 `icon` 字段迁移为多组 `tags` 标签（图标+文字+位置）。

· icon=mall_* → tag{icon, text=最高级商场名(取自分级清单), pos="left"}
· icon=hsr    → tag{icon, text="", pos="left"}（深圳北站若在商场清单里，
                追加第二组 {最高级商场袋, 商场名}）
· icon=airport→ tag{icon, text="宝安机场", pos="left"}（即用户示例「✈️ 宝安机场」）
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

def parse_malls():
    """站名 -> [(tier, 商场名), ...]（按清单出现顺序）。"""
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
    malls = parse_malls()
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    stations = doc["stations"]

    def mall_for(key):
        """站名 → 清单条目（兼容 深圳北站/深圳北、机场(T3)/机场）。"""
        cands = {key, key[:-1] if key.endswith("站") else key,
                 key.replace("(T3)", "")}
        for c in cands:
            if c in malls:
                return malls[c]
        return None

    backup = DATA.with_name(f"stations.json.bak_tags_{time.strftime('%H%M%S')}")
    shutil.copy2(DATA, backup)
    print(f"备份 -> {backup.name}")

    n_conv, n_mall_name, n_both, n_missing = 0, 0, 0, []
    for key, st in stations.items():
        old = str(st.pop("icon", None) or "")
        tags = list(st.get("tags") or [])     # 幂等：上轮已迁移的站接着补文字
        mall_entry = mall_for(key)

        if old == "hsr" and not any(t.get("icon") == "hsr" for t in tags):
            tags.insert(0, {"icon": "hsr", "text": "", "pos": "left"})
        elif old == "airport" and not any(t.get("icon") == "airport" for t in tags):
            tags.insert(0, {"icon": "airport", "text": "宝安机场", "pos": "left"})
        elif old.startswith("mall_") and not tags:
            tags.append({"icon": old, "text": "", "pos": "left"})

        if mall_entry:
            best = min((t for t, _ in mall_entry), key=lambda x: TIER_RANK[x])
            name = next(nm for t, nm in mall_entry if t == best)
            name = re.sub(r"【[^】]*】\s*$", "", name).strip()   # 去掉【地下直达】尾巴
            # 已有商场组 → 补文字；否则追加一组（高铁站 = 高铁+商场 双组并存）
            for t in tags:
                if str(t.get("icon", "")).startswith("mall_"):
                    t["icon"] = TIER_ICON[best]
                    t["text"] = name
                    break
            else:
                if any(t.get("icon") == "hsr" for t in tags):
                    n_both += 1
                else:
                    n_mall_name += 1
                tags.append({"icon": TIER_ICON[best], "text": name, "pos": "left"})

        if tags:
            st["tags"] = tags
            n_conv += 1
        elif old:
            n_missing.append(key)

    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已迁移 tags：{n_conv} 站（商场名已填 {n_mall_name}，高铁+商场双组 {n_both}）")
    print(f"有旧 icon 但没生成任何标签：{n_missing}")
    for k in ("后海", "大剧院", "深圳北站", "机场(T3)"):
        print(f"  {k}: {json.dumps(stations[k].get('tags'), ensure_ascii=False)}")

if __name__ == "__main__":
    main()
