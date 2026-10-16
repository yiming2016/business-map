# -*- coding: utf-8 -*-
"""v2.6.76：按豪宅分级清单给站点追加 mansion_* 标签（最高级楼盘名）。

清单格式（与商场/酒店不同）：分级在**段落标题**里——
  ==== S级·顶奢标杆级（单价15万/㎡以上） ====
  【南山区】
  - 登良站：深圳湾一号、中信城开信悦湾、...
映射（与商场/酒店一致）：S→红  A→金  B→紫  C→绿。
一站跨多级（如红树湾站 S+A）→ 只取**最高级**，文字取该级第一个楼盘。
已有 tags（商场/酒店等）的站追加在后面。幂等：已有 mansion 组只更新。
"""
import json
import re
import shutil
import time
from pathlib import Path

TXT = Path(r"C:/Users/29773/Pictures/豪宅/新建 文本文档.txt")
DATA = Path(r"C:/software/subway/软件/data/stations.json")

TIER_RANK = {"S": 1, "A": 2, "B": 3, "C": 4}
TIER_ICON = {"S": "mansion_red", "A": "mansion_gold",
             "B": "mansion_purple", "C": "mansion_green"}


def parse_mansions():
    """返回 {站名(不带'站'字): [(tier, 楼盘名), ...]}，跨级取并集。"""
    out = {}
    cur = None
    for line in TXT.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        m = re.match(r"=+\s*([SABC])级", s)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"-\s*(\S+?)站：(.+)", s)
        if m and cur:
            name = m.group(1)
            for part in re.split(r"[、，]", m.group(2)):
                part = part.strip()
                if part:
                    out.setdefault(name, []).append((cur, part))
    return out


def mansion_for(key, mansions):
    cands = {key, key[:-1] if key.endswith("站") else key,
             key.replace("(T3)", "")}
    if "机场" in cands:
        cands.add("机场(T3)")
    for c in cands:
        if c in mansions:
            return mansions[c]
    return None


def main():
    mansions = parse_mansions()
    print(f"清单解析：{len(mansions)} 站")
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    stations = doc["stations"]

    backup = DATA.with_name(f"stations.json.bak_mansion_{time.strftime('%H%M%S')}")
    shutil.copy2(DATA, backup)
    print(f"备份 -> {backup.name}")

    applied, missing = [], []
    for key, st in stations.items():
        entry = mansion_for(key, mansions)
        if entry is None:
            continue
        best = min((t for t, _ in entry), key=lambda x: TIER_RANK[x])
        name = next(nm for t, nm in entry if t == best)
        tags = list(st.get("tags") or [])
        for t in tags:
            if str(t.get("icon", "")).startswith("mansion_"):
                t["icon"] = TIER_ICON[best]
                t["text"] = name
                break
        else:
            tags.append({"icon": TIER_ICON[best], "text": name, "pos": "left"})
        st["tags"] = tags
        applied.append((key, best, name))

    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已配豪宅标签：{len(applied)} 站")
    for k, t, nm in sorted(applied, key=lambda x: {"S": 0, "A": 1, "B": 2, "C": 3}[x[1]]):
        print(f"  {k} = {t}级 {nm}")
    # 清单里有、库里没有的站（报告不编造）
    have = set()
    for key in stations:
        for c in (key, key[:-1] if key.endswith("站") else key,
                  key.replace("(T3)", "")):
            have.add(c)
    miss = sorted(set(mansions) - have)
    print(f"清单有但库里没有：{miss}")
    for k in ("后海", "深圳北站", "红树湾南", "机场(T3)"):
        if k in stations:
            print(f"  {k}.tags = {json.dumps(stations[k].get('tags'), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
