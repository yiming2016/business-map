"""
tools/preview_map.py
========================
把当前 stations.json + lines.json 渲染成一张预览图，
用于人工核对坐标是否合理（不需要启动 GUI）。

输出：preview.png（1600×1600）
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS_PATH = SRC_ROOT / "data" / "stations.json"
LINES_PATH = SRC_ROOT / "data" / "lines.json"
OUT = SRC_ROOT / "preview.png"

SCENE = 8000.0
OUT_SIZE = 1600
K = OUT_SIZE / SCENE  # 缩放系数


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def get_font(size):
    for name in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    with open(STATIONS_PATH, "r", encoding="utf-8") as f:
        stations = json.load(f)["stations"]
    with open(LINES_PATH, "r", encoding="utf-8") as f:
        lines = json.load(f)["lines"]

    img = Image.new("RGB", (OUT_SIZE, OUT_SIZE), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # 1) 画线路
    for ln in lines:
        color = hex2rgb(ln["color"])
        seq = ln.get("stations") or []
        pts = []
        for name in seq:
            st = stations.get(name)
            if not st:
                continue
            pts.append((st["x"] * K, st["y"] * K))
        if len(pts) >= 2:
            d.line(pts, fill=color, width=4, joint="curve")

    # 2) 画站点
    for st in stations.values():
        x, y = st["x"] * K, st["y"] * K
        if st.get("is_transfer"):
            d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 255, 255), outline=(20, 20, 20), width=2)
        else:
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 255, 255), outline=(90, 90, 90), width=1)

    # 3) 标注换乘站名（图中重点核对对象）
    fnt = get_font(13)
    for st in stations.values():
        if not st.get("is_transfer"):
            continue
        x, y = st["x"] * K, st["y"] * K
        d.text((x + 7, y - 7), st["station_name"], fill=(10, 10, 10), font=fnt)

    img.save(OUT)
    print(f"[OK] 预览图已保存: {OUT}")
    print(f"  站点 {len(stations)} 个，线路 {len(lines)} 条")


if __name__ == "__main__":
    main()
