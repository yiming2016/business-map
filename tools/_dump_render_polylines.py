# -*- coding: utf-8 -*-
"""把**软件真正画出来的**每条线的点列导成 JSON，交给 PIL 画对照图。

★ 为什么不让画图脚本自己去读数据拼点列：那样画的是"我认为软件怎么画"，
  而不是"软件真的怎么画"（自己再写一遍实现 ⇒ 改坏了也看不出来）。
  这里直接调 `ui.map_view.build_line_points_ex` —— 和渲染同一份代码。

用法：
    python tools/_dump_render_polylines.py <输出.json>
"""
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC / "_tmp_polylines.json"
    from PySide6.QtWidgets import QApplication                        # noqa: F401
    app = QApplication.instance() or QApplication(sys.argv[:1])        # noqa: F841
    from ui.map_view import build_line_points_ex

    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj
    res = []
    for L in lines:
        lid = str(L.get("id"))
        seq = [n for n in (L.get("stations") or []) if n in st]
        if len(seq) < 2:
            continue
        pts, _ebl = build_line_points_ex(lid, seq, st)
        # ★ v2.6.61：真正画出来的线是**八向化之后**的折线（渲染走
        #   build_octilinear_path）。只导原始点列，图上就看不到八向化的效果。
        try:
            from ui import metro_render as MR
            pts = [p for p, _ in MR.octilinear_waypoints_tagged(pts, _ebl)]
        except Exception:
            pass
        res.append({
            "id": lid,
            "name": L.get("name") or lid,
            "color": L.get("color") or "#808080",
            "pts": [[round(float(p.x()), 1), round(float(p.y()), 1)] for p in pts],
        })
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("[导出] %d 条线 → %s" % (len(res), out.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
