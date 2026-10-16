"""
tools/ocr_stations.py
================================
对原图做中文 OCR，把"印在图上"的站名连同它的像素位置一起读出来。

为什么要做这个：
  线路连线的顺序依赖"站名 → 坐标"。之前靠人工估坐标 + 就近吸附，
  结果不少站点被吸附到了"隔壁站"的标记上，线路就画得七拐八绕。
  直接从图上读站名位置，才能拿到唯一可靠的对应关系。

做法：
  1. 把 8000×8000 的原图切成 1000×1000 的小块（带 120 重叠，避免切断文字）；
  2. 全白的块直接跳过（省时间）；
  3. 每块丢给 OCR，把结果换算回原图坐标；
  4. 同一个站名在不同块里重复识别 → 去重，保留置信度最高的。

输出：data/ocr_labels.json
    [{"text": "竹子林", "x": ..., "y": ..., "score": 0.99, "box": [[..]]}, ...]

用法：
    python tools/ocr_stations.py
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent

TILE = 1000
OVERLAP = 120
STEP = TILE - OVERLAP
DARK_MIN = 0.0025          # 块内深色像素占比低于此值 → 空块，跳过


def main():
    from rapidocr_onnxruntime import RapidOCR

    ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
    W, H = ref.size
    full = np.array(ref)

    print("初始化 OCR 引擎 ...", flush=True)
    t0 = time.time()
    eng = RapidOCR()
    print(f"引擎就绪（{time.time() - t0:.1f}s）", flush=True)

    xs = list(range(0, W, STEP))
    ys = list(range(0, H, STEP))
    total = len(xs) * len(ys)
    print(f"切块 {len(xs)}×{len(ys)} = {total} 块，尺寸 {TILE}，重叠 {OVERLAP}", flush=True)

    raw = []
    done = skipped = 0
    t0 = time.time()
    for iy, y0 in enumerate(ys):
        for ix, x0 in enumerate(xs):
            y1 = min(y0 + TILE, H)
            x1 = min(x0 + TILE, W)
            tile = full[y0:y1, x0:x1]
            # 空块预筛：深色像素太少就不必跑 OCR
            gray = tile.mean(axis=2)
            if float((gray < 140).mean()) < DARK_MIN:
                skipped += 1
                done += 1
                continue
            try:
                res, _ = eng(tile)
            except Exception as exc:                       # noqa: BLE001
                print(f"  [!] 块({x0},{y0}) 识别失败: {exc}", flush=True)
                res = None
            for box, text, score in (res or []):
                px = min(p[0] for p in box) + x0
                py = min(p[1] for p in box) + y0
                pw = max(p[0] for p in box) - min(p[0] for p in box)
                ph = max(p[1] for p in box) - min(p[1] for p in box)
                raw.append({
                    "text": text.strip(),
                    "x": round(float(px), 1),
                    "y": round(float(py), 1),
                    "w": round(float(pw), 1),
                    "h": round(float(ph), 1),
                    "score": round(float(score), 3),
                })
            done += 1
            if done % 10 == 0 or done == total:
                el = time.time() - t0
                print(f"  {done}/{total} 块  已出 {len(raw)} 条  "
                      f"耗时 {el:.0f}s  预计剩余 {el / done * (total - done):.0f}s", flush=True)

    print(f"OCR 完成：{len(raw)} 条，跳过空块 {skipped}", flush=True)

    # 去重：同一段文字被相邻块重复识别 → 位置接近且文字相同，保留置信度最高的
    raw.sort(key=lambda r: -r["score"])
    kept = []
    for r in raw:
        dup = False
        for k in kept:
            if k["text"] != r["text"]:
                continue
            if abs(k["x"] - r["x"]) < 40 and abs(k["y"] - r["y"]) < 40:
                dup = True
                break
        if not dup:
            kept.append(r)

    kept.sort(key=lambda r: (r["y"], r["x"]))
    out = SRC / "data" / "ocr_labels.json"
    out.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"去重后 {len(kept)} 条 → {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
