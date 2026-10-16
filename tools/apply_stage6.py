# -*- coding: utf-8 -*-
"""门3 补漏 第3轮：2号线只到莲塘（与 8号线梧桐山南 贯通运营 = 虚拟换乘）。
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
    shutil.copy(p, "%s.bak_stage6_%s" % (p, TS))

S = json.load(open(SP, encoding="utf-8"))
L = json.load(open(LP, encoding="utf-8"))
ST = S["stations"]
LINES = L["lines"]


def seq(lid):
    for l in LINES:
        if str(l["id"]) == lid:
            return l["stations"]
    raise KeyError(lid)


print("2号线只到莲塘；梧桐山南改成「与 8号线贯通」的虚拟换乘")
s2 = seq("2")
if "梧桐山南" in s2:
    s2.remove("梧桐山南")
    print("  站序：2号线 移除 梧桐山南（剩 %d 站）" % len(s2))
# 梧桐山南仍标 2/8（贯通运营，同一列车），但不进 2号线站序
ST["梧桐山南"]["lines"] = ["8", "2"]
ST["梧桐山南"]["is_transfer"] = True
print("  线属：梧桐山南 → ['8', '2']（虚拟换乘，不进 2号线站序）")

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入（备份 .bak_stage6_%s）" % TS)

VIRTUAL = {("新澜", "4"), ("坪山高铁站", "16"), ("未来城", "14"), ("龙背", "16"), ("梧桐山南", "2")}
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
        if nm in seq(lid) or (nm, lid) in VIRTUAL:
            continue
        err.append("%s 的 lines 含 %s，但 %s号线站序里没有它" % (nm, lid, lid))
print("自检：%d 站 / %d 线 / %d 站次；错误 %d 条" % (len(ST), len(LINES), tot, len(err)))
for e in err:
    print("  ✗", e)
if not err:
    print("  ✓ 自洽（虚拟换乘 %d 处）" % len(VIRTUAL))
