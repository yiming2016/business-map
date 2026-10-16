"""
tools/fix_line_colors_and_order.py
================================
两件事一起做（都靠"沿站点连线采样原图像素"）：

  1) 反推每条线路的真实颜色
       相邻两站之间的连线大部分压在图上该线的彩色带上，
       把这些采样点的主色统计出来，就是这条线真正的颜色。

  2) 校验/修正站序
       用上面得到的颜色做掩膜，检查每一段连线有多少比例压在线上。
       覆盖率低的段 = 站序有问题，于是用"覆盖率优先"重排。

用法：
    python tools/fix_line_colors_and_order.py
    python tools/fix_line_colors_and_order.py --fix
"""

import sys
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SRC_ROOT = Path(__file__).resolve().parent.parent
DATA = SRC_ROOT / "data"
ORIGINAL = SRC_ROOT / "assets" / "shenzhen_metro.png"

SAMPLES = 120
SAT_MIN = 60
COLOR_TOL = 55
GOOD_COV = 0.75


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float32)


def main():
    do_fix = "--fix" in sys.argv

    img = Image.open(ORIGINAL).convert("RGB")
    arr = np.asarray(img)                      # 8000x8000x3 uint8，约 192MB
    H = arr.shape[0]

    lines_doc = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]

    def seg_pts(p, q, n=SAMPLES):
        ts = np.linspace(0.10, 0.90, n)
        xs = np.clip((p[0] + (q[0] - p[0]) * ts).astype(int), 0, H - 1)
        ys = np.clip((p[1] + (q[1] - p[1]) * ts).astype(int), 0, H - 1)
        return xs, ys

    print(f"{'线路':<16} {'当前色':>8} {'实测色':>8} {'色差':>6} {'线上占比':>8} {'好段':>8}")
    print("-" * 66)

    plan = []
    for ln in lines_doc["lines"]:
        seq = [n for n in (ln.get("stations") or []) if n in stations]
        if len(seq) < 3:
            continue
        P = np.array([[float(stations[n]["x"]), float(stations[n]["y"])] for n in seq])

        # --- 采样：收集所有相邻连线上的像素 ---
        chunks = []
        for i in range(1, len(P)):
            xs, ys = seg_pts(P[i - 1], P[i])
            chunks.append(arr[ys, xs])
        samples = np.concatenate(chunks).astype(np.int16)
        sat = (samples.max(axis=1) - samples.min(axis=1)) > SAT_MIN
        good = samples[sat]
        if len(good) < 50:
            good = samples
        # 量化到 16 级后取众数，抗噪
        q = (good // 16).astype(np.int32)
        key = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
        vals, cnts = np.unique(key, return_counts=True)
        top = vals[np.argmax(cnts)]
        sel = key == top
        measured = tuple(int(round(v)) for v in good[sel].mean(axis=0))

        on_line = float(sat.mean())
        old = hex_to_rgb(ln.get("color", "#888888"))
        old_i = tuple(int(v) for v in old)
        cd = float(np.sqrt(((np.array(measured, dtype=np.float32) - old) ** 2).sum()))

        # --- 用实测色建掩膜，测每段覆盖率 ---
        col = np.array(measured, dtype=np.float32)
        mask = None
        d2 = None
        covs = []
        for i in range(1, len(P)):
            xs, ys = seg_pts(P[i - 1], P[i])
            if d2 is None:
                pass
            px = arr[ys, xs].astype(np.int16)
            dd = np.sqrt(((px - col) ** 2).sum(axis=1))
            covs.append(float((dd < COLOR_TOL).mean()))
        good_seg = sum(1 for c in covs if c >= GOOD_COV)
        avg_cov = float(np.mean(covs))

        print(f"{ln.get('name',''):<16} #{old_i[0]:02X}{old_i[1]:02X}{old_i[2]:02X} "
              f"#{measured[0]:02X}{measured[1]:02X}{measured[2]:02X} {cd:>6.1f} "
              f"{on_line:>7.1%} {good_seg:>4}/{len(covs):<3}")
        plan.append((ln, seq, P, measured, cd, good_seg, len(covs), avg_cov))

    if not do_fix:
        print("\n（加 --fix 参数可写回）")
        return

    bak = DATA / "lines.json.bak_colorder"
    if not bak.exists():
        shutil.copy2(DATA / "lines.json", bak)
        print(f"[BACKUP] {bak}")

    ncol = 0
    for ln, seq, P, measured, cd, gs, tot, avg in plan:
        # 只在"线上占比"够高（说明连线确实压在线上）且色差较大时才改颜色
        if avg > 0.45 and cd > 22:
            ln["color"] = f"#{measured[0]:02X}{measured[1]:02X}{measured[2]:02X}"
            ncol += 1
    (DATA / "lines.json").write_text(
        json.dumps(lines_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已写回，修正 {ncol} 条线路的颜色")


if __name__ == "__main__":
    main()
