# -*- coding: utf-8 -*-
"""v2.6.68：按用户清单（不同站点所在区）批量填充每站 district 字段。

数据源：C:/Users/29773/Pictures/新建 文本文档.txt
  格式：区名一行，下一行「站名、站名、…」（顿号分隔）。

只改 软件/data/stations.json（用户权威数据），不碰源码侧。
"""
import json
import re
import shutil
import time
from pathlib import Path

TXT = Path(r"C:/Users/29773/Pictures/新建 文本文档.txt")
DATA = Path(r"C:/software/subway/软件/data/stations.json")

DISTRICTS = ["福田区", "罗湖区", "南山区", "盐田区", "宝安区", "龙岗区", "龙华区", "坪山区", "光明区"]

# 清单里的写法 → 数据库里的实际站名（对账后再补）
ALIAS = {
    "机场": "机场(T3)",
}

def parse_txt():
    lines = [l.strip() for l in TXT.read_text(encoding="utf-8").splitlines() if l.strip()]
    mapping = {}
    cur = None
    for l in lines:
        if l in DISTRICTS:
            cur = l
            continue
        if cur is None:
            raise SystemExit(f"区名之前出现内容：{l!r}")
        for name in re.split(r"[、，,]", l):
            name = name.strip()
            if name:
                if name in mapping and mapping[name] != cur:
                    raise SystemExit(f"站 {name} 出现在两个区：{mapping[name]} / {cur}")
                mapping[name] = cur
    return mapping

def main():
    mapping = parse_txt()
    print(f"清单共 {len(mapping)} 站")

    backup = DATA.with_name(f"stations.json.bak_district_{time.strftime('%H%M%S')}")
    shutil.copy2(DATA, backup)
    print(f"备份 -> {backup.name}")

    doc = json.loads(DATA.read_text(encoding="utf-8"))
    stations = doc["stations"]

    matched = 0
    missing_in_data = []   # 清单里有、库里没有
    for name, dist in mapping.items():
        key = ALIAS.get(name, name)
        if key in stations:
            stations[key]["district"] = dist
            matched += 1
        else:
            missing_in_data.append(name)

    # 反向：库里有、清单没有 → 只报告，不擅自清空。
    unmatched = [k for k in stations if k not in mapping
                 and k not in {ALIAS.get(v) for v in mapping}]
    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 district：{matched} 站")
    print(f"清单有但库里没有：{len(missing_in_data)} -> {missing_in_data}")
    print(f"库里没有 district 的站（清单没给）：{len([k for k in stations if not stations[k].get('district')])}")
    if unmatched:
        print(f"未匹配站名（库里存在但不在清单）：{unmatched}")

if __name__ == "__main__":
    main()
