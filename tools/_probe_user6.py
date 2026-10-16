# -*- coding: utf-8 -*-
"""只读探针：核对你列的 6 个站对，到底属于哪条线、相邻不相邻、画出来什么形状。"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, line_station_xy

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
TR = doc.get("traced") or {}
OO = set(doc.get("octi_off") or [])
SS = doc.get("segment_shapes") or {}
lines = doc.get("lines") or []

PAIRS = [("国展北", "福海西"), ("福永", "桥头"), ("西乡桃源", "平峦山"),
         ("宝安", "前海湾"), ("临海", "前海湾"), ("后海", "红树湾南")]

for a, b in PAIRS:
    print("=" * 74)
    print("%s ➡ %s" % (a, b))
    if a not in st or b not in st:
        print("   站不在库里：", a if a not in st else "", b if b not in st else "")
        continue
    found = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        if a in seq and b in seq:
            i, j = seq.index(a), seq.index(b)
            found.append((lid, i, j, abs(i - j)))
    if not found:
        print("   ★ 没有任何一条线同时包含这两站")
    for lid, i, j, gap in found:
        tag = "相邻" if gap == 1 else ("隔 %d 站" % (gap - 1))
        key = "%s|%s|%s" % (lid, a, b) if i < j else "%s|%s|%s" % (lid, b, a)
        ntr = len(TR.get(key) or [])
        print("   [%s号线] %s  (idx %d->%d)  段键=%s  描线=%d点  octi_off=%s  segment_shapes=%s"
              % (lid, tag, i, j, key, ntr, "是" if key in OO else "否",
                 "有" if key in SS else "无"))
        try:
            pts, ebl = build_line_points_ex(lid, [a, b], st)
            P = [(round(p.x(), 1), round(p.y(), 1)) for p in pts]
            print("        渲染路径 %d 点: %s" % (len(P), P[:14]))
            ax, ay = line_station_xy(st[a], lid)
            bx, by = line_station_xy(st[b], lid)
            print("        站点落脚点 A=(%.1f,%.1f) B=(%.1f,%.1f)" % (ax, ay, bx, by))
            print("        首点=站点A? %s   末点=站点B? %s"
                  % (abs(P[0][0] - ax) < 0.6 and abs(P[0][1] - ay) < 0.6,
                     abs(P[-1][0] - bx) < 0.6 and abs(P[-1][1] - by) < 0.6))
        except Exception as e:
            print("        渲染失败:", repr(e))

print()
print("===== 站名在这些线上的落脚点偏移（lanes）=====")
for n in ["国展北", "福海西", "福永", "桥头", "西乡桃源", "平峦山",
          "宝安", "前海湾", "临海", "后海", "红树湾南"]:
    s = st.get(n)
    if not s:
        continue
    lanes = s.get("lanes") or {}
    print("  %-6s %s" % (n, json.dumps(lanes, ensure_ascii=False)))
