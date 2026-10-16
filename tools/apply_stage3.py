# -*- coding: utf-8 -*-
"""门3：把门1/门2 的成果正式写入业务数据（先备份！本脚本自己也会再备一份）。

做的事情：
 1) 341 个站写入按原图重取的坐标（云巴/有轨电车 30 站**完全不动**）
 2) 线属修正：国展南→[20]、国展→[12,20]、深圳湾公园→[9]、华新→[3,7]
 3) 颜色修正：4号线 #D42E12→#E71615（原图实测）、11号线 #6B1C40→#6D2041
 4) 补站：机场(11号线)、福星(11号线)，并按原图站序插进 lines.json
 5) 7号线站序插入 华新
 6) 自检 + 写 logs/门3自检.txt

回滚：源码/data/stations.json.bak_stage3_* 与 lines.json.bak_stage3_*
"""
import json
import shutil
import time
from collections import Counter

SRC = "C:/software/subway/源码"
TS = time.strftime("%Y%m%d_%H%M%S")
FROZEN = {"坪山云巴", "有轨电车", "有轨电车支线"}

ST_PATH = SRC + "/data/stations.json"
LN_PATH = SRC + "/data/lines.json"
for p in (ST_PATH, LN_PATH):
    shutil.copy(p, p + ".bak_stage3b_" + TS)

SJ = json.load(open(ST_PATH, encoding="utf-8"))
LJ = json.load(open(LN_PATH, encoding="utf-8"))
ST = SJ["stations"]
FIN = json.load(open(SRC + "/logs/_final_coords.json", encoding="utf-8"))
coord, tag = FIN["final"], FIN["tag"]

_lines = LJ["lines"] if isinstance(LJ, dict) and "lines" in LJ else LJ
_lines = _lines if isinstance(_lines, list) else list(_lines.values())
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _lines}

report = []
moved = frozen = missing = 0
for nm, s in ST.items():
    if set(s["lines"]) & FROZEN:
        frozen += 1
        continue
    p = coord.get(nm)
    if p is None:
        missing += 1
        report.append(f"  ! {nm}: 门2 没给坐标，保持原样")
        continue
    s["x"], s["y"] = round(float(p[0]), 2), round(float(p[1]), 2)
    moved += 1
report.append(f"坐标写入：改 {moved} 站；冻结不动 {frozen} 站；缺坐标 {missing} 站")

# ---------- 线属修正 ----------
LINES_FIX = {
    "国展南": ["20"],          # 用户：只属 20号线
    "国展": ["12", "20"],      # 用户：12/20 换乘
    "深圳湾公园": ["9"],       # 用户：11号线不设此站
    "华新": ["3", "7"],        # 用户：3/7 换乘
}
for nm, ls in LINES_FIX.items():
    if nm in ST:
        old = ST[nm]["lines"]
        ST[nm]["lines"] = ls
        ST[nm]["is_transfer"] = len(ls) > 1
        report.append(f"线属：{nm} {old} → {ls}")
    else:
        report.append(f"  ! 线属修正找不到站 {nm}")

# ---------- 颜色修正 ----------
COLOR_FIX = {"4": "#E71615", "11": "#6D2041"}
for l in _lines:
    lid = str(l.get("id") or l.get("line_id"))
    if lid in COLOR_FIX and l.get("color") != COLOR_FIX[lid]:
        report.append(f"颜色：{lid}号线 {l.get('color')} → {COLOR_FIX[lid]}")
        l["color"] = COLOR_FIX[lid]

# ---------- 补新站 ----------
NEW = {
    "机场": {"lines": ["11"], "x": 640, "y": 3353},      # 原图 机场北↔碧海湾 之间的白圆点
    "福星": {"lines": ["11"], "x": 3868, "y": 5284},     # 原图 岗厦北↔华强南 之间的白圆点
}
TEMPLATE_KEYS = ["station_id", "station_name", "lines", "x", "y", "is_transfer", "open_date",
                 "description", "exits", "facilities", "landmarks", "notes", "_updated_at", "timetable"]
for nm, info in NEW.items():
    if nm in ST:
        report.append(f"  ! 新站 {nm} 已存在，跳过")
        continue
    rec = {k: "" for k in TEMPLATE_KEYS}
    rec.update({"station_id": nm, "station_name": nm, "lines": info["lines"],
                "x": float(info["x"]), "y": float(info["y"]),
                "is_transfer": False, "_updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    ST[nm] = rec
    report.append(f"补站：{nm} @({info['x']},{info['y']}) 属 {'/'.join(info['lines'])}")

# ---------- 站序插入 ----------
def insert_after(lid, anchor, new):
    seq = ORDER[lid]
    if new in seq:
        report.append(f"  ! {lid}号线 已有 {new}")
        return
    i = seq.index(anchor)
    seq.insert(i + 1, new)
    l = next(x for x in _lines if str(x.get("id") or x.get("line_id")) == lid)
    for k in ("stations", "order", "stop_list"):
        if k in l:
            l[k] = seq
            break
    report.append(f"站序：{lid}号线 {anchor} 之后插入 {new}")

insert_after("11", "机场北", "机场")
insert_after("11", "岗厦北", "福星")
insert_after("7", "华强北", "华新")

# ---------- 站序移除（与线属修正保持一致）----------
REMOVE = {
    "11": ["深圳湾公园"],     # 用户确认 11号线不设此站
    "12": ["国展南", "会展城"],  # 用户给的 12号线清单里没有这两站
}
for lid, names in REMOVE.items():
    seq = ORDER[lid]
    for nm in names:
        if nm in seq:
            seq.remove(nm)
            l = next(x for x in _lines if str(x.get("id") or x.get("line_id")) == lid)
            for k in ("stations", "order", "stop_list"):
                if k in l:
                    l[k] = seq
                    break
            report.append(f"站序：{lid}号线 移除 {nm}")

json.dump(SJ, open(ST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(LJ, open(LN_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
report.append(f"已写入 {ST_PATH} 与 {LN_PATH}")

# ---------- 自检 ----------
err = []
for lid, seq in ORDER.items():
    for nm in seq:
        if nm not in ST:
            err.append(f"{lid}号线站序里的 {nm} 不在 stations.json")
        elif lid not in ST[nm]["lines"]:
            err.append(f"{lid}号线站序含 {nm}，但该站 lines={ST[nm]['lines']}")
for nm, s in ST.items():
    if not s["lines"]:
        err.append(f"{nm} 没有所属线路")
report.append(f"\n自检：{len(ST)} 站 / {len(ORDER)} 线；错误 {len(err)} 条")
for e in err[:20]:
    report.append("  ✗ " + e)
if not err:
    report.append("  ✓ 站序与 lines 字段全部自洽")

txt = "\n".join(report)
print(txt)
open(SRC + "/logs/门3自检.txt", "w", encoding="utf-8").write(txt)
