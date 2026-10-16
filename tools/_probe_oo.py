# -*- coding: utf-8 -*-
import sys, json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "软件" / "data"
sys.path.insert(0, str(ROOT))
import core.data_manager as CDM
CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"
from ui.map_view import build_line_points_ex, octi_off_paths, traced_paths
from ui import metro_render as MR

dm = CDM.get_data_manager()
st = dm.all_stations()
doc = dm.lines_doc
_oo = octi_off_paths(); _tr = traced_paths()
print("octi_off 共", len(_oo), " traced 共", len(_tr))
for key in ["13|光明城|德雅路", "5|上水径|下水径", "6|上屋|官田"]:
    lid, a, b = key.split("|")
    pts, ebl = build_line_points_ex(lid, [a, b], st)
    w = MR.octilinear_waypoints_tagged(pts, ebl)
    print("="*70)
    print(key, "in_oo=", key in _oo, "in_tr=", key in _tr)
    print(" pts n=%d ebl n=%d" % (len(pts), len(ebl)))
    for i,p in enumerate(pts):
        print("   p%-2d (%8.1f,%8.1f)  ebl=%s" % (i, p.x(), p.y(), ebl[i] if i<len(ebl) else "?"))
    print(" ebl tail:", ebl[len(pts)-1:])
    print(" waypoints n=%d" % len(w))
    for i,(p,s) in enumerate(w):
        print("   w%-2d (%8.1f,%8.1f) st=%s" % (i, p.x(), p.y(), s))
