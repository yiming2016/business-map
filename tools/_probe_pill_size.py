# -*- coding: utf-8 -*-
"""量原图换乘药丸的**实际外形尺寸**：白心宽 + 黑描边宽 → 外廓尺寸。

data 里的 pill.wid 是**白心**宽（泛洪出来的白色区域），
渲染时若直接把白心宽当外廓画，药丸就会比原图瘦一圈（描边被吃掉）。
"""
import json, math, os, sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "assets", "shenzhen_metro.png")


def main(names):
    im = Image.open(IMG).convert("RGB")
    px = im.load()
    W, H = im.size
    with open(os.path.join(ROOT, "data", "stations.json"), encoding="utf-8") as f:
        sts = list(json.load(f)["stations"].values())
    print(f"{'站名':<10}{'ang':>7}{'len内':>7}{'wid内':>7}{'wid外':>7}{'描边':>6}   剖面")
    for s in sts:
        if names and s.get("station_name") not in names:
            continue
        p = s.get("pill")
        if not p:
            continue
        cx, cy = float(s["x"]), float(s["y"])
        a = math.radians(float(p["ang"]))
        nx, ny = -math.sin(a), math.cos(a)      # 药丸的短轴方向
        # 沿短轴扫过药丸中心：白 → 黑边 → 底图
        prof = []
        for t in range(-60, 61):
            X, Y = int(round(cx + nx * t)), int(round(cy + ny * t))
            if not (0 <= X < W and 0 <= Y < H):
                prof.append("?")
                continue
            c = px[X, Y]
            if min(c) >= 244:
                prof.append("W")                      # 白心
            elif sum(c) < 200:
                prof.append("#")                      # 黑描边
            elif abs(c[0] - 247) < 9 and abs(c[1] - 249) < 9 and abs(c[2] - 251) < 9:
                prof.append(".")                      # 底图 #F7F9FB
            else:
                prof.append("o")                      # 线路
        # 白心宽度（连续最长 W 段）
        runs, cur = [], 0
        for k in prof:
            if k == "W":
                cur += 1
            elif cur:
                runs.append(cur); cur = 0
        if cur:
            runs.append(cur)
        wi = max(runs) if runs else 0
        # 外廓：白心两侧各有 "#" 段
        i0 = prof.index("W")
        j0 = len(prof) - 1 - prof[::-1].index("W")
        left = 0
        k = i0 - 1
        while k >= 0 and prof[k] in "#o":
            if prof[k] == "#":
                left += 1
            k -= 1
        right = 0
        k = j0 + 1
        while k < len(prof) and prof[k] in "#o":
            if prof[k] == "#":
                right += 1
            k += 1
        border = max(left, right)
        print(f"{s['station_name']:<10}{float(p['ang']):>7.1f}{p['len']:>7}{p['wid']:>7}"
              f"{wi + 2 * border:>7}{border:>6}   {''.join(prof[40:81])}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["车公庙", "老街", "岗厦北", "光明", "深圳北站", "布吉"])
