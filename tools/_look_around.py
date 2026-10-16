# -*- coding: utf-8 -*-
"""只读：列出指定站周围 250px 内的 ①白圆点(带偏移方向/尺寸/贴哪条线) ②图上文字(OCR)。
用来把用户口头描述的"往左下一点"翻译成具体坐标，并核对站名。
用法：python tools/_look_around.py 站名1 站名2 ...
"""
import json
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = "C:/software/subway/源码"
img = np.array(Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
OCR = json.load(open(SRC + "/data/ocr_labels.json", encoding="utf-8"))
FIN = json.load(open(SRC + "/logs/_final_coords.json", encoding="utf-8"))
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
COLOR.update({"4": "#E71615", "11": "#6D2041"})


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


DF = {}
for lid, c in COLOR.items():
    r, g, b = hex2rgb(c)
    m = (np.abs(img[:, :, 0] - r) + np.abs(img[:, :, 1] - g) + np.abs(img[:, :, 2] - b)) <= 20
    DF[lid] = ndimage.distance_transform_edt(~ndimage.binary_erosion(m, np.ones((3, 3))))

white = (np.abs(img[:, :, 0] - 254) + np.abs(img[:, :, 1] - 254) + np.abs(img[:, :, 2] - 254)) <= 12
white = ndimage.binary_erosion(white, np.ones((3, 3)))
lab, n = ndimage.label(white, np.ones((3, 3)))
area = np.bincount(lab.ravel()); sl = ndimage.find_objects(lab)
circ = []
for i, s in enumerate(sl, start=1):
    if s is None:
        continue
    a = int(area[i])
    if a < 150:
        continue
    h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
    if not (14 <= w <= 140 and 14 <= h <= 140) or a / (w * h) < 0.55:
        continue
    sub = lab[s] == i
    yy, xx = np.nonzero(sub)
    cx, cy = int(xx.mean()) + s[1].start, int(yy.mean()) + s[0].start
    touch = set()
    for lid in COLOR:
        f = DF[lid]
        d = min(float(f[cy, cx]),
                float(f[max(0, s[0].start - 3):s[0].stop + 3, max(0, s[1].start - 3):s[1].stop + 3].min()))
        if d <= 22:
            touch.add(lid)
    if touch:
        circ.append((cx, cy, w, h, touch))

for nm in sys.argv[1:]:
    p = FIN["final"].get(nm) or (ST[nm]["x"], ST[nm]["y"])
    px, py = p
    print(f"\n=== {nm}  当前点 ({px:.0f},{py:.0f})  库里线={ST[nm]['lines']} ===")
    near = [c for c in circ if abs(c[0] - px) <= 260 and abs(c[1] - py) <= 260]
    for cx, cy, w, h, t in sorted(near, key=lambda c: (c[0] - px) ** 2 + (c[1] - py) ** 2):
        dx, dy = cx - px, cy - py
        dirs = []
        if dx < -8: dirs.append("左")
        if dx > 8: dirs.append("右")
        if dy < -8: dirs.append("上")
        if dy > 8: dirs.append("下")
        print(f"   圆点 ({cx},{cy})  {w}×{h}  偏移({dx:+.0f},{dy:+.0f}) "
              f"{''.join(dirs) or '原位'}  贴 {'/'.join(sorted(t))}")
    texts = [o for o in OCR if abs(o["x"] + o["w"] / 2 - px) <= 300 and abs(o["y"] + o["h"] / 2 - py) <= 300]
    for o in sorted(texts, key=lambda o: (o["x"] + o["w"] / 2 - px) ** 2 + (o["y"] + o["h"] / 2 - py) ** 2)[:12]:
        print(f"   文字「{o['text']}」 @({o['x'] + o['w'] / 2:.0f},{o['y'] + o['h'] / 2:.0f})")
