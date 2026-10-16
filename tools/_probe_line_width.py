# -*- coding: utf-8 -*-
"""把「原图」与「我们的渲染」在**同一位置**的线宽量出来对比。

做法：用 tools/_render_check.py 的 multi 出图（上排=我们，下排=原图），
      在两张 tile 的同一场景点做垂直/水平剖面，数该线颜色的像素个数。
tile 映射：scene [c-165, c+165] → [0, TILE]
"""
import os, sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLORS = {
    "1": (0, 176, 82), "2": (186, 87, 0), "3": (0, 166, 222), "4": (231, 22, 21),
    "5": (158, 77, 171), "6": (0, 196, 181), "6支": (0, 138, 128), "7": (0, 51, 171),
    "8": (186, 87, 0), "9": (138, 107, 112), "10": (252, 108, 151), "11": (109, 32, 65),
    "12": (168, 145, 176), "13": (212, 133, 0), "14": (237, 204, 97),
    "16": (64, 18, 166), "20": (153, 219, 222),
}


def thickness(px, W, H, x0, y0, dx, dy, ref, tol=70):
    """从 (x0,y0) 沿 (dx,dy) 方向走 ±80 步，数匹配像素个数（=线宽）。"""
    n = 0
    for t in range(-80, 81):
        X, Y = int(round(x0 + dx * t)), int(round(y0 + dy * t))
        if not (0 <= X < W and 0 <= Y < H):
            continue
        c = px[X, Y]
        if sum(abs(c[k] - ref[k]) for k in range(3)) < tol:
            n += 1
    return n


def main():
    names = sys.argv[1:] or ["车公庙"]
    sheet = Image.open(os.path.join(ROOT, "logs", "_render_compare_sheet.png")).convert("RGB")
    # 反推 tile 尺寸：multi 出图时 TILE 由 HALF=165 / VS=0.54 / out_scale 决定，
    # 这里直接用图宽和站数反推（PAD=8）。
    n = 6 if sheet.width == 2084 else int(sys.argv[0] and 6)
    PAD, LBL = 8, 24
    TILE = (sheet.width - (n + 1) * PAD) // n
    vs = TILE / 330.0
    print(f"tile={TILE}px 覆盖 330 场景单位 ⇒ 有效缩放 {vs:.3f}")

    import json
    with open(os.path.join(ROOT, "data", "stations.json"), encoding="utf-8") as f:
        st = json.load(f)["stations"]
    orig = Image.open(os.path.join(ROOT, "assets", "shenzhen_metro.png")).convert("RGB")

    print(f"{'站名':<8}{'线':<4}{'原图线宽':>9}{'我们的':>8}{'倍数':>7}")
    for i, nm in enumerate(names):
        s = st.get(nm)
        if not s:
            continue
        cx, cy = float(s["x"]), float(s["y"])
        for lid, v in (s.get("lanes") or {}).items():
            ref = COLORS.get(lid)
            if not ref:
                continue
            lang = float(v[2])
            import math
            a = math.radians(lang)
            nx, ny = -math.sin(a), math.cos(a)      # 法向（量厚度）
            # 取药丸外侧一点作为剖面中心
            half = float((s.get("pill") or {}).get("len", 50)) * 0.5
            ux, uy = math.cos(a), math.sin(a)
            px_, py_ = cx + ux * (half + 30), cy + uy * (half + 30)
            t_orig = thickness(orig.load(), orig.width, orig.height, px_, py_, nx, ny, ref)
            # 我们那张 tile
            tx, ty = int((px_ - (cx - 165)) * vs), int((py_ - (cy - 165)) * vs)
            c2 = sheet.crop((PAD + i * (TILE + PAD), LBL,
                             PAD + i * (TILE + PAD) + TILE, LBL + TILE)).convert("RGB")
            t_mine = thickness(c2.load(), c2.width, c2.height, tx, ty, nx, ny, ref)
            print(f"{nm:<8}{lid:<4}{t_orig:>9}{t_mine:>8}{t_orig / max(t_mine, 1):>7.2f}")


if __name__ == "__main__":
    main()
