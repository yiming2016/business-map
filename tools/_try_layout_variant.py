# -*- coding: utf-8 -*-
"""
_try_layout_variant.py —— 临时试一组布局参数，量化它对**站名压线**的影响。

用途：布局重排（`relayout_octilinear.py`）动的是坐标，而坐标一动，
      站名的排版结果（压线率、能显示几个站名）也会跟着变。
      光看布局指标不够 —— 必须把坐标换进去，真跑一次排版，才算数。

★ 安全：本脚本只**临时**改写 `data/stations.json`，跑完一定还原；
      且 `_chk_label_on_line.py` 自己会拷副本到临时目录，不会写真数据。

用法：
    python tools/_try_layout_variant.py <名字> <参数 JSON>
例：
    python tools/_try_layout_variant.py V2 '{"dmin":0.85,"w_sep":14.0}'
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = sys.executable

ST = ROOT / "data" / "stations.json"
KEEP = ROOT / "logs" / "_cur_v2616.json"

from tools.relayout_octilinear import build_edges, dist, load, metrics  # noqa: E402


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "V"
    kw = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    if not KEEP.exists():
        shutil.copy2(ST, KEEP)

    st, ln = load()
    edges = build_edges(ln)
    old = {n: (v["x"], v["y"]) for n, v in st.items()}
    baseL = sum(dist(old[a], old[b]) for _, a, b in edges) / len(edges)

    from tools.relayout_octilinear import relayout
    new = relayout(st, ln, baseL, 1.0, iters=10, anchor=0.35, penalty=0.3,
                   length_mode="perline", w_perp=kw.get("w_perp", 8.0),
                   w_par=1.0, dmin=kw.get("dmin", 0.6) * baseL,
                   w_sep=kw.get("w_sep", 10.0), w_clamp=60.0,
                   lmin_f=kw.get("lmin_f", 0.6), lmax_f=kw.get("lmax_f", 2.0))
    m = metrics(new, ln, edges)
    print(f"[{name}] 布局: CV {m['间距CV']:.3f}  八向 {m['八向5']*100:.1f}%  "
          f"毛刺 {m['毛刺']}  直线 {m['直线度']*100:.1f}%  "
          f"非邻min {m['非邻最小']:.1f}  过近 {m['过近对']}  宽高比 {m['宽高比']:.2f}")

    # 写进去跑一次真排版
    data = json.load(open(KEEP, encoding="utf-8"))
    for n, v in data["stations"].items():
        if n in new:
            v["x"] = round(new[n][0], 2)
            v["y"] = round(new[n][1], 2)
    json.dump(data, open(ST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    try:
        out = subprocess.run([PY, str(ROOT / "tools" / "_chk_label_on_line.py")],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=600).stdout
        for line in out.splitlines():
            if ("避让=True" in line or "缩到最小" in line
                    or "站名数 开避让" in line or "FAIL" in line):
                print(f"[{name}]   {line.strip()}")
    finally:
        shutil.copy2(KEEP, ST)
        print(f"[{name}] 已还原 {ST.name}")


if __name__ == "__main__":
    main()
