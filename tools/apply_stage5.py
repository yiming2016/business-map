# -*- coding: utf-8 -*-
"""门3 补漏 第2轮（用户逐条反馈）：
A 深圳北 → 深圳北站
B 8号线去掉莲塘，梧桐山南改 2/8 换乘（2号线延伸到梧桐山南）
C 有轨电车 新澜 可换 4号线（虚拟换乘，走 50m 到观澜）
D 坪山云巴：补坪山中心；坪山高铁站换16、坪山中心换14、未来城换14、龙背换16
写前自动备份。
"""
import json
import shutil
import time

SRC = "C:/software/subway/源码"
TS = time.strftime("%Y%m%d_%H%M%S")
SP = SRC + "/data/stations.json"
LP = SRC + "/data/lines.json"
for p in (SP, LP):
    shutil.copy(p, "%s.bak_stage5_%s" % (p, TS))

S = json.load(open(SP, encoding="utf-8"))
L = json.load(open(LP, encoding="utf-8"))
ST = S["stations"]
LINES = L["lines"]


def line(lid):
    for l in LINES:
        if str(l["id"]) == lid:
            return l
    raise KeyError(lid)


def seq(lid):
    return line(lid)["stations"]


# ---------------- A 站名：深圳北 → 深圳北站 ----------------
print("A. 站名 深圳北 → 深圳北站")
OLD, NEW = "深圳北", "深圳北站"
if OLD in ST:
    new_st = {}
    for k, v in ST.items():
        if k == OLD:
            v = dict(v)
            v["station_name"] = NEW
            new_st[NEW] = v
        else:
            new_st[k] = v
    S["stations"] = new_st
    ST = new_st
    print("  stations.json：%s → %s（%s）" % (OLD, NEW, ST[NEW]["lines"]))
for l in LINES:
    if OLD in l["stations"]:
        i = l["stations"].index(OLD)
        l["stations"][i] = NEW
        print("  %s号线站序第 %d 站改名" % (l["id"], i + 1))


def insert_after(lid, after, nm):
    s = seq(lid)
    if nm in s:
        print("  站序 %s 已有 %s，跳过" % (lid, nm))
        return
    s.insert(s.index(after) + 1, nm)
    print("  站序：%s号线 %s 之后插入 %s" % (lid, after, nm))


def remove(lid, nm):
    s = seq(lid)
    if nm in s:
        s.remove(nm)
        print("  站序：%s号线 移除 %s" % (lid, nm))


def set_lines(nm, ls):
    s = ST[nm]
    old = list(s["lines"])
    s["lines"] = ls
    s["is_transfer"] = len(ls) > 1
    print("  线属：%s %s → %s" % (nm, old, ls))


# ---------------- B 8号线 莲塘 / 梧桐山南 ----------------
print("B. 8号线 与 2号线 的换乘点")
remove("8", "莲塘")
set_lines("莲塘", ["2"])
set_lines("梧桐山南", ["8", "2"])
insert_after("2", "莲塘", "梧桐山南")

# ---------------- C 有轨电车 新澜 → 可换 4号线 ----------------
print("C. 有轨电车 新澜 虚拟换乘 4号线")
set_lines("新澜", ["有轨电车", "4"])

# ---------------- D 坪山云巴 ----------------
print("D. 坪山云巴")
insert_after("坪山云巴", "文化聚落", "坪山中心")
set_lines("坪山中心", ["14", "坪山云巴"])
set_lines("坪山高铁站", ["坪山云巴", "16"])
set_lines("未来城", ["坪山云巴", "14"])
set_lines("龙背", ["坪山云巴", "16"])

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入 stations.json / lines.json（备份 .bak_stage5_%s）" % TS)

# ---------------- 自检 ----------------
# 虚拟换乘：站名不同、只是"走几十米能换"，所以不进对方线路的站序，属正常
VIRTUAL = {("新澜", "4"), ("坪山高铁站", "16"), ("未来城", "14"), ("龙背", "16")}
print("自检：")
err = []
tot = 0
for l in LINES:
    lid = str(l["id"])
    for nm in l["stations"]:
        tot += 1
        if nm not in ST:
            err.append("%s号线站序含 库里没有的站 %s" % (lid, nm))
        elif lid not in ST[nm]["lines"]:
            err.append("%s号线站序含 %s（lines=%s）" % (lid, nm, ST[nm]["lines"]))
for nm, s in ST.items():
    for lid in s["lines"]:
        if nm in seq(lid):
            continue
        if (nm, lid) in VIRTUAL:
            continue
        err.append("%s 的 lines 含 %s，但 %s号线站序里没有它" % (nm, lid, lid))
print("  %d 站 / %d 线 / %d 站次；错误 %d 条" % (len(ST), len(LINES), tot, len(err)))
for e in err:
    print("  ✗", e)
if not err:
    print("  ✓ 站序与 lines 字段全部自洽（虚拟换乘 %d 处已白名单）" % len(VIRTUAL))
