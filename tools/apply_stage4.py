# -*- coding: utf-8 -*-
"""门3补漏（对照用户给的逐线清单）：
A 补 5 个漏站进站序   B 修 4 处线属   C 修国展南坐标
写前自动备份 stations.json / lines.json。
"""
import json
import shutil
import time

SRC = "C:/software/subway/源码"
TS = time.strftime("%Y%m%d_%H%M%S")
SP = SRC + "/data/stations.json"
LP = SRC + "/data/lines.json"
for p in (SP, LP):
    shutil.copy(p, "%s.bak_stage4_%s" % (p, TS))

S = json.load(open(SP, encoding="utf-8"))
L = json.load(open(LP, encoding="utf-8"))
ST = S["stations"]
LINES = L["lines"]


def line(lid):
    for l in LINES:
        if str(l["id"]) == lid:
            return l
    raise KeyError(lid)


def insert_after(lid, after, nm):
    seq = line(lid)["stations"]
    if nm in seq:
        print("  站序 %s 已有 %s，跳过" % (lid, nm))
        return
    seq.insert(seq.index(after) + 1, nm)
    print("  站序：%s号线 %s 之后插入 %s" % (lid, after, nm))


def insert_before(lid, before, nm):
    seq = line(lid)["stations"]
    if nm in seq:
        print("  站序 %s 已有 %s，跳过" % (lid, nm))
        return
    seq.insert(seq.index(before), nm)
    print("  站序：%s号线 %s 之前插入 %s" % (lid, before, nm))


print("A. 补漏站")
insert_after("12", "太子湾", "海上世界")     # 海上世界 @(1202,6599) 贴 12 号线
insert_after("12", "福海西", "国展")         # 国展 @(440,2300)  12/20
insert_after("12", "朗下", "松岗")           # 松岗 @(926,1224)  6/11/12
insert_before("13", "歌剧院", "东角头")       # 东角头 @(1598,6624) 药丸=换乘，最南端
insert_after("10", "岗厦北", "岗厦")         # 岗厦 @(3715,5374) 药丸=换乘，10 号线竖线经过

print("B. 线属修正")
LINES_FIX = {
    "海上世界": ["2", "12"],
    "松岗": ["6", "11", "12"],
    "东角头": ["2", "13"],
    "岗厦": ["1", "10"],
}
for nm, ls in LINES_FIX.items():
    s = ST[nm]
    old = list(s["lines"])
    s["lines"] = ls
    s["is_transfer"] = len(ls) > 1
    print("  线属：%s %s → %s" % (nm, old, ls))

print("C. 坐标修正")
COORD_FIX = {"国展南": (415, 2574)}          # 原写成国展的同一点 (440,2300)
for nm, (x, y) in COORD_FIX.items():
    s = ST[nm]
    print("  坐标：%s (%d,%d) → (%d,%d)" % (nm, s["x"], s["y"], x, y))
    s["x"], s["y"] = float(x), float(y)

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入 stations.json / lines.json（备份 .bak_stage4_%s）" % TS)

# ---------- 自检 ----------
print("自检：")
err = []
nst = len(ST)
nln = len(LINES)
tot = 0
for l in LINES:
    lid = str(l["id"])
    seq = l["stations"]
    tot += len(seq)
    for nm in seq:
        if nm not in ST:
            err.append("%s号线站序含 库里没有的站 %s" % (lid, nm))
            continue
        if lid not in ST[nm]["lines"]:
            err.append("%s号线站序含 %s（lines=%s）" % (lid, nm, ST[nm]["lines"]))
for nm, s in ST.items():
    for lid in s["lines"]:
        seq = line(lid)["stations"]
        if nm not in seq:
            err.append("%s 的 lines 含 %s，但 %s号线站序里没有它" % (nm, lid, lid))
print("  %d 站 / %d 线 / %d 站次；错误 %d 条" % (nst, nln, tot, len(err)))
for e in err:
    print("  ✗", e)
if not err:
    print("  ✓ 站序与 lines 字段全部自洽")
