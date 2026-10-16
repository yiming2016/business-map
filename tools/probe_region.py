"""在指定像素区域内，列出检测到的站点标记与 OCR 文本，人工核对坐标。

用法: python tools/probe_region.py x0 y0 x1 y1
"""
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"

x0, y0, x1, y1 = (float(v) for v in sys.argv[1:5])

markers = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
labels = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))

print(f"=== 区域 ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) ===")
print("--- 站点标记（含形状/填充率），按 y 排序 ---")
ms = [m for m in markers if x0 <= m["x"] <= x1 and y0 <= m["y"] <= y1]
ms.sort(key=lambda m: (m["y"], m["x"]))
for m in ms:
    print(f"  ({m['x']:>7.1f},{m['y']:>7.1f})  {m['w']:>3}x{m['h']:<3} fill={m['fill']:.2f}")

print("--- OCR 文本（2~8 字中文），按 y 排序 ---")
ls = [l for l in labels if x0 <= l["x"] + l["w"] / 2 <= x1 and y0 <= l["y"] + l["h"] / 2 <= y1]
ls = [l for l in ls if 2 <= len(l["text"]) <= 8]
ls.sort(key=lambda l: (l["y"], l["x"]))
for l in ls:
    cx, cy = l["x"] + l["w"] / 2, l["y"] + l["h"] / 2
    print(f"  {l['text']:<12s} 中心({cx:>7.1f},{cy:>7.1f})  框 x[{l['x']:.0f},{l['x']+l['w']:.0f}] y[{l['y']:.0f},{l['y']+l['h']:.0f}] s={l['score']:.2f}")
