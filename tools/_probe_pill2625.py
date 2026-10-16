# -*- coding: utf-8 -*-
"""v2.6.25 只读探针：药丸半长 vs 该站最外侧走廊外缘，看"左右各遮住一点"成不成立。"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from ui.metro_render import StationDotItem, LINE_W_SCENE

d = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "stations.json"), encoding="utf-8"))
st = d["stations"]
names = ["科学馆", "车公庙", "老街", "前海湾", "深圳北站", "世界之窗", "福田口岸", "布吉"]

for s in (0.10, 0.16, 0.25, 0.54, 1.0):
    print("=== view_scale = %.2f" % s)
    for n in names:
        if n not in st:
            continue
        it = StationDotItem(n, dict(st[n]))
        it.apply_view_scale(s)
        hw, hl = it.pill_half()
        span = it.lane_span_along()
        outer = (span * 0.5 + LINE_W_SCENE * 0.5) * s
        print("  %-6s hw=%5.2f hl=%6.2f | span=%6.1f 外缘=%5.2f 超出=%6.2f"
              % (n, hw, hl, span, outer, hl - outer))
