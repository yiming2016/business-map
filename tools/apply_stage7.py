# -*- coding: utf-8 -*-
"""门3 第4轮（用户拍板：不要右下角小图，把云巴/电车塞进主图）：
A 修正 4号线清湖坐标（原图圆点 3043,2887；数据里错写成 3045,3053）
B 把 坪山云巴 / 有轨电车 / 有轨电车支线 的坐标写成原图主图真值
C 写入 6 条「虚拟换乘」（不在同一站体，走几十~几百米）
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
    shutil.copy(p, "%s.bak_stage7_%s" % (p, TS))

S = json.load(open(SP, encoding="utf-8"))
L = json.load(open(LP, encoding="utf-8"))
ST = S["stations"]
LINES = L["lines"]
OFF = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126",
                     encoding="utf-8"))["stations"]


def seq(lid):
    for l in LINES:
        if str(l["id"]) == lid:
            return l["stations"]
    raise KeyError(lid)


# ---------------- A 清湖 ----------------
print("A. 4号线清湖：原图圆点实测 (3043,2887) 贴 4号线色×1047")
old = (ST["清湖"]["x"], ST["清湖"]["y"])
ST["清湖"]["x"], ST["清湖"]["y"] = 3043.0, 2887.0
print("   清湖 (%d,%d) → (3043,2887)   [有轨电车清湖另有站体 (3075,2920)，相距约46px≈50m]"
      % (old[0], old[1]))

# ---------------- B 云巴 / 电车坐标 ----------------
print("B. 云巴 / 电车 坐标（取原图主图真值备份）")
KEEP = {"清湖", "坪山中心"}      # 同名站：坐标以地铁线为准，不覆盖
n = 0
for lid in ("坪山云巴", "有轨电车", "有轨电车支线"):
    for nm in seq(lid):
        if nm in KEEP or nm not in OFF:
            continue
        o = OFF[nm]
        ST[nm]["x"], ST[nm]["y"] = float(o["x"]), float(o["y"])
        n += 1
print("   写入 %d 站坐标" % n)

# ---------------- C 虚拟换乘 ----------------
print("C. 虚拟换乘")
VT = {
    "清湖": [{"station": "清湖", "line": "4", "distance": "约50米",
             "note": "4号线清湖站 与 有轨电车清湖站 是两个站体"}],
    "新澜": [{"station": "观澜", "line": "4", "distance": "约50米"}],
    "坪山高铁站": [{"station": "坪山", "line": "16", "distance": "约100米"}],
    "坪山中心": [{"station": "坪山中心", "line": "14", "distance": "约450米",
               "note": "14号线 与 坪山云巴 的坪山中心不是同一站体"}],
    "未来城": [{"station": "坪山广场", "line": "14", "distance": "约450米"}],
    "龙背": [{"station": "东纵纪念馆", "line": "16", "distance": "约500米"}],
}
REV = {
    "观澜": [{"station": "新澜", "line": "有轨电车", "distance": "约50米"}],
    "坪山": [{"station": "坪山高铁站", "line": "坪山云巴", "distance": "约100米"}],
    "坪山广场": [{"station": "未来城", "line": "坪山云巴", "distance": "约450米"}],
    "东纵纪念馆": [{"station": "龙背", "line": "坪山云巴", "distance": "约500米"}],
}
for nm, v in VT.items():
    ST[nm]["virtual_transfer"] = v
    print("   %-8s → %s（%s）" % (nm, v[0]["station"], v[0]["distance"]))
for nm, v in REV.items():
    cur = ST[nm].get("virtual_transfer") or []
    ST[nm]["virtual_transfer"] = cur + v
    print("   %-8s ← %s（%s）" % (nm, v[0]["station"], v[0]["distance"]))

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入（备份 .bak_stage7_%s）" % TS)

# ---------------- 自检 ----------------
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
# 相邻站距离异常（同一条线上相邻两站 > 900px 报警）
for l in LINES:
    s = l["stations"]
    for a, b in zip(s, s[1:]):
        if a not in ST or b not in ST:
            continue
        d = ((ST[a]["x"] - ST[b]["x"]) ** 2 + (ST[a]["y"] - ST[b]["y"]) ** 2) ** 0.5
        if d > 900:
            err.append("%s号线 %s→%s 相距 %.0fpx，异常" % (l["id"], a, b, d))
print("自检：%d 站 / %d 线 / %d 站次；错误 %d 条" % (len(ST), len(LINES), tot, len(err)))
for e in err:
    print("  ✗", e)
if not err:
    print("  ✓ 自洽")
