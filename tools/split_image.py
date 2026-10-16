"""
tools/split_image.py
========================
把 8000x8000 原图切成 NxN 块并缩放，便于逐块精读坐标。
"""

import sys
from pathlib import Path
from PIL import Image

SRC_ROOT = Path(__file__).resolve().parent.parent
IMG = SRC_ROOT / "assets" / "shenzhen_metro.png"
OUTDIR = SRC_ROOT / "_tiles"


def main():
    nx = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out_size = int(sys.argv[2]) if len(sys.argv) > 2 else 1200

    OUTDIR.mkdir(exist_ok=True)
    img = Image.open(IMG).convert("RGB")
    W, H = img.size
    tw, th = W // nx, H // nx
    for iy in range(nx):
        for ix in range(nx):
            box = (ix * tw, iy * th, (ix + 1) * tw, (iy + 1) * th)
            tile = img.crop(box).resize((out_size, out_size), Image.LANCZOS)
            name = OUTDIR / f"tile_{iy}_{ix}.png"
            tile.save(name)
            print(f"{name}   场景范围 x:[{box[0]},{box[2]}] y:[{box[1]},{box[3]}]")


if __name__ == "__main__":
    main()
