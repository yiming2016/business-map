"""
体检：站点坐标落点附近到底有哪些线路颜色？
若站点声明的线路颜色在身边找不到 → 说明"站名 ↔ 坐标"错位。
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)

LEGEND = {
    "1":  (0x00, 0xB0, 0x52), "2":  (0xBA, 0x57, 0x00), "3":  (0x00, 0xA6, 0xDE),
    "4":  (0xD4, 0x2E, 0x12), "5":  (0x9E, 0x4D, 0xAB), "6":  (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7":  (0x00, 0x33, 0xAB), "8":  (0xBA, 0x57, 0x00),
    "9":  (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
}
LEG = {k: np.array(v, dtype=np.int16) for k, v in LEGEND.items()}

st = json.loads((SRC / "data/stations.json").read_text(encoding="utf-8"))["stations"]

def ring_colors(x, y, r_in=16, r_out=46):
    """统计圆心周围环形区域里各线路颜色的占比。"""
    x, y = int(round(x)), int(round(y))
    y0, y1 = max(0, y - r_out), min(img.shape[0], y + r_out + 1)
    x0, x1 = max(0, x - r_out), min(img.shape[1], x + r_out + 1)
    patch = img[y0:y1, x0:x1].astype(np.int16)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - y) ** 2 + (xx - x) ** 2
    sel = patch[(d2 >= r_in ** 2) & (d2 <= r_out ** 2)]
    if len(sel) == 0:
        return {}
    out = {}
    for k, c in LEG.items():
        dd = np.abs(sel - c).max(axis=1)
        frac = float((dd <= 42).mean())
        if frac > 0.01:
            out[k] = round(frac, 3)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))

bad = []
for sid, s in st.items():
    hits = ring_colors(s["x"], s["y"])
    declared = set(s.get("lines") or [])
    if not declared:
        continue
    top = list(hits)[:3]
    ok = declared & set(hits)
    if not ok:
        bad.append((sid, sorted(declared), top, hits))
    elif not (declared <= set(hits)):
        bad.append((sid, sorted(declared), top, hits))

print(f"共 {len(st)} 站，可疑 {len(bad)} 站")
print("-" * 78)
for sid, dec, top, hits in bad[:60]:
    print(f"{sid:<8} 声明={','.join(dec):<10} 实测={hits}")
