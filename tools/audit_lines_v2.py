"""
tools/audit_lines_v2.py
================================
用（已修正的）站点坐标，读"这个站点标记周围到底有哪几条线路经过"。

这是修正线路归属的依据：如果声明里写 1 号线、但标记旁边根本没有 1 号线的
颜色，说明这条线路的归属写错了。

用法：
    python tools/audit_lines_v2.py            # 总览 + 问题清单
    python tools/audit_lines_v2.py --json     # 把观测结果存成 data/observed_lines.json
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent

LEGEND = {
    "1": (0x00, 0xB0, 0x52), "2": (0xBA, 0x57, 0x00), "3": (0x00, 0xA6, 0xDE),
    "4": (0xD4, 0x2E, 0x12), "5": (0x9E, 0x4D, 0xAB), "6": (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7": (0x00, 0x33, 0xAB), "8": (0xBA, 0x57, 0x00),
    "9": (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
}
# 原图里同色的线路，只能合并判断
SAME = [("2", "8")]        # 2 号线与 8 号线同色
R_IN, R_OUT = 20, 56
THRESH = 0.10


def main():
    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    stations = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))["lines"]
    declared_by_line = {ln["id"]: set(ln.get("stations") or []) for ln in lines}

    def observe(x, y):
        x, y = int(round(x)), int(round(y))
        y0, y1 = max(0, y - R_OUT), min(H, y + R_OUT + 1)
        x0, x1 = max(0, x - R_OUT), min(W, x + R_OUT + 1)
        patch = img[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d2 = (yy - y) ** 2 + (xx - x) ** 2
        sel = patch[(d2 >= R_IN ** 2) & (d2 <= R_OUT ** 2)]
        frac = {}
        for lid, c in LEGEND.items():
            dd = np.abs(sel - np.array(c, dtype=np.int16)).max(axis=1)
            f = float((dd <= 20).mean())
            if f > 0.004:
                frac[lid] = round(f, 4)
        return frac

    observed = {}
    for sid, s in stations.items():
        observed[sid] = observe(s["x"], s["y"])

    # 合并同色线路：2/8 合成一个色组
    def to_groups(frac, thresh):
        out = set()
        f2 = dict(frac)
        pair = {k: v for k, v in f2.items() if k in ("2", "8")}
        if pair:
            f2["2/8"] = max(pair.values())
        f2.pop("8", None)
        for k, v in f2.items():
            if v >= thresh:
                out.add(k)
        return out, f2

    def declared_groups(sid):
        g = set()
        for l in (stations[sid].get("lines") or []):
            g.add("2/8" if l in ("2", "8") else l)
        return g

    problems = []
    for sid in stations:
        obs, _ = to_groups(observed[sid], THRESH)
        dec = declared_groups(sid)
        missing = dec - obs          # 声明了但看不到 → 可能写错
        extra = obs - dec            # 看到了但没声明 → 可能漏写
        if missing or extra:
            problems.append((sid, dec, obs, missing, extra, observed[sid]))

    print(f"站点 {len(stations)} 个，线路归属可疑 {len(problems)} 个")
    print("=" * 96)
    print(f"{'站点':<10}{'声明':<16}{'实测':<16}{'声明了但看不到':<18}{'看到了但没声明'}")
    print("-" * 96)
    for sid, dec, obs, missing, extra, frac in sorted(problems, key=lambda r: -len(r[2])):
        top = sorted(frac.items(), key=lambda kv: -kv[1])[:4]
        print(f"{sid:<10}{'/'.join(sorted(dec)):<16}{'/'.join(sorted(obs)):<16}"
              f"{'/'.join(sorted(missing)):<18}{'/'.join(sorted(extra))}"
              f"   [{' '.join(k+':'+format(v,'.2f') for k, v in top)}]")

    if "--json" in sys.argv:
        out = SRC / "data" / "observed_lines.json"
        out.write_text(json.dumps(observed, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n观测结果 → {out}")


if __name__ == "__main__":
    main()
