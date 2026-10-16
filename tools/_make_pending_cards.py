# -*- coding: utf-8 -*-
"""把 DP/OCR/吸附 三法不一致的站做成"看图选 A/B"的卡片，让用户一句话就能回。
每张卡片：红圈=方案A（我推荐）  蓝圈=方案B  黄圈=旧坐标  绿框=图上站名文字位置
"""
import json
import difflib
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

SRC = "C:/software/subway/源码"
img0 = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")
img = np.array(img0).astype(np.int16)
ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
OCR = json.load(open(SRC + "/data/ocr_labels.json", encoding="utf-8"))
dp = json.load(open(SRC + "/logs/_assign_dp.json", encoding="utf-8"))
ocr = json.load(open(SRC + "/logs/_assign_by_ocr.json", encoding="utf-8"))
snap = json.load(open(SRC + "/logs/_resnap_v2.json", encoding="utf-8"))


def norm(s):
    return "".join(ch for ch in s.strip() if ch not in " 　:：·.、-—")


name2ocr = {}
for o in OCR:
    t = norm(o["text"])
    if t in ST:
        name2ocr.setdefault(t, []).append(o)

pending = dp["conflict"] + [(nm, None) for nm in dp["miss"] if nm not in [c[0] for c in dp["conflict"]]]
print(f"待定站 {len(pending)} 个")

# 圆点全集（用于画候选）
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
    circ.append((int(xx.mean()) + s[1].start, int(yy.mean()) + s[0].start, w, h))

lines = []
R = 190
for idx, (nm, per) in enumerate(pending, 1):
    s = ST[nm]
    # 候选点：DP各线结果 / OCR / 吸附 / 旧坐标
    cands, seen = [], set()
    src = []
    if per:
        for lid, p in per.items():
            src.append((f"{lid}号线DP", tuple(p)))
    if nm in ocr:
        src.append(("OCR", tuple(ocr[nm]["circle"])))
    if nm in snap:
        src.append(("吸附", tuple(snap[nm]["new"])))
    src.append(("旧坐标", (round(s["x"]), round(s["y"]))))
    for tag, p in src:
        if p not in seen:
            seen.add(p); cands.append((tag, p))
    # 画面中心：优先站名文字框，否则旧坐标
    if nm in name2ocr:
        o = name2ocr[nm][0]
        cx, cy = o["x"] + o["w"] / 2, o["y"] + o["h"] / 2
    else:
        cx, cy = s["x"], s["y"]
    x0, y0, x1, y1 = int(cx - R), int(cy - R), int(cx + R), int(cy + R)
    im = img0.crop((x0, y0, x1, y1)).resize((2 * (x1 - x0), 2 * (y1 - y0)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    for tag, p in cands:
        X, Y = (p[0] - x0) * 2, (p[1] - y0) * 2
        col = {"旧坐标": (255, 200, 0), "OCR": (255, 0, 0), "吸附": (0, 120, 255)}.get(
            tag, (255, 0, 0) if tag.endswith("DP") else (0, 200, 0))
        d.ellipse([X - 26, Y - 26, X + 26, Y + 26], outline=col, width=5)
        d.text((X + 28, Y - 10), tag, fill=col)
    if nm in name2ocr:
        o = name2ocr[nm][0]
        d.rectangle([(o["x"] - x0) * 2, (o["y"] - y0) * 2,
                     (o["x"] + o["w"] - x0) * 2, (o["y"] + o["h"] - y0) * 2],
                    outline=(0, 170, 0), width=4)
    for (ccx, ccy, w, h) in circ:
        if x0 <= ccx < x1 and y0 <= ccy < y1:
            X, Y = (ccx - x0) * 2, (ccy - y0) * 2
            d.ellipse([X - 3, Y - 3, X + 3, Y + 3], fill=(0, 0, 0))
    fn = f"待定站{idx:02d}_{nm}.png"
    im.save(SRC + "/logs/" + fn)
    opts = "  ".join(f"{t}=({p[0]},{p[1]})" for t, p in cands)
    lines.append(f"### {idx}. {nm}　（属 {'/'.join(s['lines'])} 线）\n"
                 f"![{fn}]({fn})\n"
                 f"候选：{opts}\n\n**问：红圈(OCR/DP) 和 蓝圈(吸附) 哪个是这个站？还是都不对（你说坐标）？**\n")

open(SRC + "/logs/待定站清单.md", "w", encoding="utf-8").write(
    "# 只剩这 %d 个站定不下来 —— 看图选 A/B 就行\n\n"
    "图例：**红圈**=按图上站名文字认领的坐标　**蓝圈**=按旧坐标吸附的坐标　"
    "**黄圈**=现在的旧坐标　**绿框**=图上站名文字　**黑点**=图上所有检出的圆点\n\n"
    % len(pending) + "\n".join(lines))
print("已写出 logs/待定站清单.md 与", len(pending), "张卡片")
