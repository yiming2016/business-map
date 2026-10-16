# -*- coding: utf-8 -*-
"""把"我算出来的站点位置"直接画到原图上，做成一张对照图给用户看。
红点=已确定的站；黄圈+黄点=还拿不准、请你重点看的站；绿点=云巴/电车(保持原样不动)。

用法：python tools/_make_review_overlay.py
产物：logs/复核_全图.png + logs/复核_分区1..4.png
"""
import json
import sys
import numpy as np
from PIL import Image, ImageDraw

SRC = "C:/software/subway/源码"
FROZEN = {"坪山云巴", "有轨电车", "有轨电车支线"}

ST = json.load(open(SRC + "/data/stations.json.bak_relayout_20260930_021126", encoding="utf-8"))["stations"]
try:
    for k, v in json.load(open(SRC + "/logs/_lines_fix.json", encoding="utf-8")).items():
        ST[k]["lines"] = v
except Exception:
    pass
dp = json.load(open(SRC + "/logs/_assign_dp.json", encoding="utf-8"))
ocr = json.load(open(SRC + "/logs/_assign_by_ocr.json", encoding="utf-8"))
snap = json.load(open(SRC + "/logs/_resnap_v2.json", encoding="utf-8"))
lj = json.load(open(SRC + "/data/lines.json", encoding="utf-8"))
_l = lj["lines"] if isinstance(lj, dict) and "lines" in lj else lj
_l = _l if isinstance(_l, list) else list(_l.values())
COLOR = {str(l.get("id") or l.get("line_id")): l.get("color") for l in _l}
ORDER = {str(l.get("id") or l.get("line_id")): (l.get("stations") or l.get("order") or []) for l in _l}

# ---------- 汇总最终坐标（--rebuild 时才重算）----------
REBUILD = "--rebuild" in sys.argv
final, tag = {}, {}
for nm, s in ST.items():
    if set(s["lines"]) & FROZEN:
        final[nm] = (s["x"], s["y"]); tag[nm] = "frozen"
    elif nm in dp["merged"]:
        final[nm] = tuple(dp["merged"][nm]); tag[nm] = "ok"
    elif nm in ocr:
        final[nm] = tuple(ocr[nm]["circle"]); tag[nm] = "pending"
    elif nm in snap:
        final[nm] = tuple(snap[nm]["new"]); tag[nm] = "pending"
    else:
        final[nm] = (s["x"], s["y"]); tag[nm] = "pending"

# 人工裁定
final["岗厦北"] = (3715, 5122); tag["岗厦北"] = "ok"
final["深圳湾公园"] = (2616, 5874); tag["深圳湾公园"] = "ok"


# ---------- 自愈：某条线出现"两站抢同一点"（说明该线圆点漏检导致 DP 塌缩）
# → 这条线整体改用 OCR 认领结果（OCR 认领 0 冲突，更稳）
def line_has_dup(lid):
    seen = set()
    for nm in ORDER.get(lid, []):
        p = final.get(nm)
        if p is None:
            continue
        if p in seen:
            return True
        seen.add(p)
    return False


healed = []
for lid in ORDER:
    if lid in FROZEN or not line_has_dup(lid):
        continue
    healed.append(lid)
    for nm in ORDER[lid]:
        if nm in ocr:
            final[nm] = tuple(ocr[nm]["circle"]); tag[nm] = "ok"
        elif nm in snap:
            final[nm] = tuple(snap[nm]["new"]); tag[nm] = "pending"
if healed:
    print(f"[自愈] 抢点线改用 OCR 结果：{'、'.join(healed)}")

# 同一条线内两个站抢到同一个圆点 → 标记待确认（14号线圆点漏检会引发）
dup = []
for lid, seq in ORDER.items():
    if lid in FROZEN:
        continue
    seen = {}
    for nm in seq:
        p = final.get(nm)
        if p is None:
            continue
        if p in seen:
            tag[nm] = "pending"; tag[seen[p]] = "pending"
            dup.append((lid, seen[p], nm, p))
        else:
            seen[p] = nm
print(f"抢点冲突 {len(dup)} 组：")
for d in dup:
    print("   ", d)
print(f"已确定 {sum(1 for t in tag.values() if t=='ok')} 站；"
      f"待确认 {sum(1 for t in tag.values() if t=='pending')} 站；"
      f"冻结 {sum(1 for t in tag.values() if t=='frozen')} 站")
if REBUILD:
    json.dump({"final": {k: list(v) for k, v in final.items()}, "tag": tag},
              open(SRC + "/logs/_final_coords.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- 画图 ----------
if not REBUILD:      # 用 _apply_feedback.py 修正过的结果，别重新推导把它覆盖掉
    _f = json.load(open(SRC + "/logs/_final_coords.json", encoding="utf-8"))
    final = {k: tuple(v) for k, v in _f["final"].items()}
    tag = dict(_f["tag"])
    print(f"读取已修正坐标：ok={sum(1 for t in tag.values() if t=='ok')} "
          f"moved={sum(1 for t in tag.values() if t=='moved')} "
          f"unknown={sum(1 for t in tag.values() if t=='unknown')} "
          f"frozen={sum(1 for t in tag.values() if t=='frozen')}")

base = Image.open(SRC + "/assets/shenzhen_metro.png").convert("RGB")


def draw(im, sc):
    d = ImageDraw.Draw(im)
    for nm, (x, y) in final.items():
        X, Y = x * sc, y * sc
        t = tag[nm]
        if t == "frozen":
            d.ellipse([X - 5, Y - 5, X + 5, Y + 5], fill=(0, 170, 80))
            continue
        lid = ST[nm]["lines"][0]
        col = COLOR.get(lid, "#000000")
        r = 5
        d.ellipse([X - r, Y - r, X + r, Y + r], fill=col, outline=(0, 0, 0))
        if t in ("pending", "unknown"):
            col2 = (255, 0, 255) if t == "unknown" else (255, 200, 0)
            d.ellipse([X - 11, Y - 11, X + 11, Y + 11], outline=col2, width=3)
            d.text((X + 12, Y - 8), nm, fill=col2)
    return im


full = base.resize((2000, 2000), Image.LANCZOS)
draw(full, 0.25).save(SRC + "/logs/复核_全图.png")
print("复核_全图.png")

quad = [("复核_分区1_左上.png", (0, 0, 4000, 4000)), ("复核_分区2_右上.png", (4000, 0, 8000, 4000)),
        ("复核_分区3_左下.png", (0, 4000, 4000, 8000)), ("复核_分区4_右下.png", (4000, 4000, 8000, 8000))]
for fn, (x0, y0, x1, y1) in quad:
    im = base.crop((x0, y0, x1, y1)).resize((2000, 2000), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    for nm, (x, y) in final.items():
        if not (x0 <= x < x1 and y0 <= y < y1):
            continue
        X, Y = (x - x0) * 0.5, (y - y0) * 0.5
        t = tag[nm]
        if t == "frozen":
            d.ellipse([X - 5, Y - 5, X + 5, Y + 5], fill=(0, 170, 80)); continue
        col = COLOR.get(ST[nm]["lines"][0], "#000000")
        d.ellipse([X - 6, Y - 6, X + 6, Y + 6], fill=col, outline=(0, 0, 0))
        if t in ("pending", "unknown"):
            col2 = (255, 0, 255) if t == "unknown" else (255, 200, 0)
            d.ellipse([X - 16, Y - 16, X + 16, Y + 16], outline=col2, width=5)
            d.text((X + 18, Y - 12), nm, fill=col2)
    im.save(SRC + "/logs/" + fn)
    print(fn)
