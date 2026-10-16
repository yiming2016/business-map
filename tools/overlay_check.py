"""
tools/overlay_check.py
================================
把数据里的站点坐标叠加到原图上，检查坐标是否与原图站点重合。
这是判断"坐标准不准"最直接的证据。

用法：
    python tools/overlay_check.py [输出路径] [叠加图边长]
"""

import sys
import json
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None

SRC_ROOT = Path(__file__).resolve().parent.parent
DATA = SRC_ROOT / "data"
ORIGINAL = SRC_ROOT / "assets" / "shenzhen_metro.png"


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (SRC_ROOT / "overlay.png")
    side = int(sys.argv[2]) if len(sys.argv) > 2 else 1600

    stations = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    img = Image.open(ORIGINAL).convert("RGB")
    W, H = img.size
    k = side / W
    img = img.resize((side, int(H * k)), Image.LANCZOS)

    d = ImageDraw.Draw(img)
    n = 0
    for sid, st in stations.items():
        x = float(st.get("x", 0)) * k
        y = float(st.get("y", 0)) * k
        r = 4
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 0, 255), width=2)
        n += 1
    img.save(str(out))
    print(f"[OK] 叠加了 {n} 个站点 → {out}  ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
