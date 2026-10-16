# -*- coding: utf-8 -*-
"""门3 第6轮（用户澄清：不是换乘站，是「虚线连接 + 线上标米数」）：

1) 不同站之间（新澜↔观澜 等）→ 顶层 transfer_links，两站各自回归单线，不再是换乘站
2) 同名两个站体（清湖/湖贝/红岭南/坪山中心）→ 站记录内 alt_bodies（第二个站体的坐标+所属线），
   站本身 is_transfer=False，两站体之间画虚线（有米数的标米数）
3) 梧桐山南：8号线 与 2号线 贯通 → 回归单线 ['8']，lines.json 里给 8号线加 "through":"2"（实线直通）

说明：lines 字段保留"该站涉及哪些线路的站序"；is_transfer 才决定画不画换乘图标。
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
    shutil.copy(p, "%s.bak_stage9_%s" % (p, TS))

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


# ---------- 1) 不同站之间的虚线 ----------
print("1) 不同站之间：改成虚线连接，两站回归普通站")
BACK = {                      # 站 → 只保留自己真正的线路
    "新澜": ["有轨电车"],
    "坪山高铁站": ["坪山云巴"],
    "未来城": ["坪山云巴"],
    "龙背": ["坪山云巴"],
    "梧桐山南": ["8"],
}
for nm, ls in BACK.items():
    old = list(ST[nm]["lines"])
    ST[nm]["lines"] = ls
    ST[nm]["is_transfer"] = False
    ST[nm].pop("virtual_transfer", None)
    print("   %-8s lines %s → %s（不再是换乘站）" % (nm, old, ls))
for nm in ("观澜", "坪山", "坪山广场", "东纵纪念馆"):
    ST[nm].pop("virtual_transfer", None)

S["transfer_links"] = [
    {"a": "新澜", "b": "观澜", "distance": "约50米"},
    {"a": "坪山高铁站", "b": "坪山", "distance": "约100米"},
    {"a": "未来城", "b": "坪山广场", "distance": "约450米"},
    {"a": "龙背", "b": "东纵纪念馆", "distance": "约450米"},   # 原图 @x=7407 标「约450米」
]
print("   transfer_links: " + "；".join("%s↔%s %s" % (d["a"], d["b"], d["distance"])
                                     for d in S["transfer_links"]))

# ---------- 2) 同名两个站体 ----------
print("2) 同名两个站体：加 alt_bodies，站本身改成普通站")
ALT = {
    "清湖":     [{"x": 3076, "y": 2921, "line": "有轨电车", "distance": "约50米"}],
    "湖贝":     [{"x": 5015, "y": 5034, "line": "5", "distance": ""}],        # 原图未标米数
    "红岭南":   [{"x": 4503, "y": 5500, "line": "9", "distance": ""}],        # 原图未标米数
    "坪山中心": [{"x": 7120, "y": 2699, "line": "坪山云巴", "distance": "约500米"}],  # 原图 @x=6488 标「约500米」
}
for nm, bodies in ALT.items():
    ST[nm]["alt_bodies"] = bodies
    ST[nm]["is_transfer"] = False
    ST[nm].pop("virtual_transfer", None)
    print("   %-8s 主站体(%d,%d) 副站体 %s %s"
          % (nm, ST[nm]["x"], ST[nm]["y"],
             "(%d,%d)" % (bodies[0]["x"], bodies[0]["y"]),
             bodies[0]["distance"] or "（不标米数）"))

# ---------- 3) 8号线与2号线贯通 ----------
print("3) 8号线 与 2号线 贯通（按一条线连）")
line("8")["through"] = "2"
print("   8号线 加 through=2；梧桐山南 lines=['8']，2号线仍只到莲塘")

json.dump(S, open(SP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(L, open(LP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已写入（备份 .bak_stage9_%s）" % TS)

# ---------- 自检 ----------
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
        if nm not in seq(lid):
            err.append("%s 的 lines 含 %s，但 %s号线站序里没有它" % (nm, lid, lid))
for d in S.get("transfer_links", []):
    for k in ("a", "b"):
        if d[k] not in ST:
            err.append("transfer_links 里的 %s=%s 不在库里" % (k, d[k]))
for nm, s in ST.items():
    for b in s.get("alt_bodies", []):
        if b["line"] not in s["lines"]:
            err.append("%s 的 alt_body 线路 %s 不在本站 lines %s 里" % (nm, b["line"], s["lines"]))
        if nm not in seq(b["line"]):
            err.append("%s 不在 %s号线站序里，但有个 %s 的副站体" % (nm, b["line"], b["line"]))
print("自检：%d 站 / %d 线 / %d 站次；错误 %d 条" % (len(ST), len(LINES), tot, len(err)))
for e in err:
    print("  ✗", e)
if not err:
    print("  ✓ 自洽")
