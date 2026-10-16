"""从原图检测「站点标记」，并判定它所归属的线路颜色。

标记定义 = 一块小白斑，四周被"线色环"完整包围。
  -> 环形像素中非白占比 >= 0.90 且 颜色一致性高 => 站标
  -> 环上出现多种颜色（黑字+白底）=> 文字空洞，丢弃
输出 data/markers2.json：{x, y, w, h, ring_color, kind}
  kind: 'disc' 小圆(普通站) / 'capsule' 圆角长条(换乘站)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

REGION = (100, 600, 7920, 7100)
MIN_SIDE, MAX_SIDE = 12, 80
MIN_AREA, MAX_AREA = 150, 9000
WHITE_MIN = 215
RING_NONWHITE = float(sys.argv[sys.argv.index("--ring") + 1]) if "--ring" in sys.argv else 0.88
CSTD_MAX = float(sys.argv[sys.argv.index("--cstd") + 1]) if "--cstd" in sys.argv else 150.0


def main():
    img = Image.open(IMG).convert("RGB")
    L, T, R, B = REGION
    a = np.asarray(img.crop((L, T, R, B))).astype(np.int16)
    print(f"工作区 {a.shape[1]}x{a.shape[0]}")

    mx = a.max(axis=2)
    white = mx >= WHITE_MIN
    lab, n = ndimage.label(white)
    objs = ndimage.find_objects(lab)

    ring_k = ndimage.generate_binary_structure(2, 2)
    res = []
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
            continue
        m = (lab[sl] == i)
        area = int(m.sum())
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        fill = area / float(w * h)
        if fill < 0.55:
            continue

        # 环形带：把白斑膨胀几像素再减去自身
        pad = 6
        y0 = max(0, sl[0].start - pad); y1 = min(lab.shape[0], sl[0].stop + pad)
        x0 = max(0, sl[1].start - pad); x1 = min(lab.shape[1], sl[1].stop + pad)
        big = np.zeros((y1 - y0, x1 - x0), bool)
        sub = (lab[y0:y1, x0:x1] == i)
        big |= ndimage.binary_dilation(sub, ring_k, iterations=pad)
        ring_mask = big & ~sub
        ring_px = a[y0:y1, x0:x1][ring_mask]
        if len(ring_px) < 30:
            continue
        nonwhite = (ring_px.max(axis=1) < 240).mean()
        if nonwhite < RING_NONWHITE:
            continue
        # 环色一致性：用各通道标准差之和衡量
        cstd = float(ring_px.std(axis=0).sum())
        if cstd > CSTD_MAX:
            continue
        col = np.median(ring_px, axis=0).astype(int)
        kind = "capsule" if max(w, h) / max(1, min(w, h)) > 1.45 else "disc"
        res.append({
            "x": round(float(sl[1].start + w / 2 + L), 1),
            "y": round(float(sl[0].start + h / 2 + T), 1),
            "w": int(w), "h": int(h), "area": area,
            "fill": round(float(fill), 3),
            "ring": "#%02X%02X%02X" % tuple(int(v) for v in col),
            "cstd": round(cstd, 1),
            "kind": kind,
        })

    res.sort(key=lambda r: (round(r["y"] / 50), r["x"]))
    print(f"站标候选: {len(res)}  其中 disc={sum(1 for r in res if r['kind']=='disc')} "
          f"capsule={sum(1 for r in res if r['kind']=='capsule')}")
    (DATA / "markers2.json").write_text(
        json.dumps({"markers": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] -> {DATA / 'markers2.json'}")

    # 叠加图
    side = 1800
    k = side / img.size[0]
    vis = img.resize((side, side), Image.LANCZOS)
    from PIL import ImageDraw
    d = ImageDraw.Draw(vis)
    for r in res:
        x, y = r["x"] * k, r["y"] * k
        col = (255, 0, 255) if r["kind"] == "disc" else (0, 200, 0)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=col, width=2)
    vis.save(str(SRC / "_markers2_vis.png"))
    print(f"[OK] 叠加图 -> {SRC / '_markers2_vis.png'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
