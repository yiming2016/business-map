# -*- coding: utf-8 -*-
"""核实"走廊偏移 (dx,dy) 的符号方向"是否与原图一致。

★ 关键：原图里线路走到换乘站时会被白色药丸盖住，所以不能在站点中心附近采样。
  做法：在药丸**外侧**（沿走廊方向 |t| 在 [半长+15, 半长+130] 区间），
        对每个横向偏移 s 统计该线颜色命中数，取加权中心 → 即该走廊真实偏移。
  再与 data/stations.json 的 lanes 值比对（都投影到走廊法向上）。
不用眼睛看图，直接出数字。
"""
import json, math, os, sys
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "assets", "shenzhen_metro.png")


def load():
    with open(os.path.join(ROOT, "data", "stations.json"), encoding="utf-8") as f:
        st = json.load(f)["stations"]
    with open(os.path.join(ROOT, "data", "lines.json"), encoding="utf-8") as f:
        ln = json.load(f)["lines"]
    colors = {}
    for L in ln:
        c = L["color"].lstrip("#")
        colors[L["id"]] = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    return list(st.values()), colors


def main(names, tol=90):
    im = Image.open(IMG).convert("RGB")
    px = im.load()
    W, H = im.size
    sts, COLORS = load()
    for s in sts:
        nm = s.get("station_name")
        if nm not in names:
            continue
        cx, cy = float(s["x"]), float(s["y"])
        pill = s.get("pill") or {}
        lanes = s.get("lanes") or {}
        half = float(pill.get("len", 50.0)) * 0.5
        print(f"\n=== {nm}  center=({cx:.1f},{cy:.1f})  pill ang={pill.get('ang')} len={pill.get('len')}")
        for lid, v in lanes.items():
            dx, dy, ang, el = float(v[0]), float(v[1]), float(v[2]), float(v[3])
            ref = COLORS.get(lid)
            if ref is None:
                print(f"  line {lid}: 没颜色，跳过")
                continue
            a = math.radians(ang)
            ux, uy = math.cos(a), math.sin(a)      # 走廊方向
            nx, ny = -uy, ux                       # 法向
            proj = dx * nx + dy * ny               # 数据偏移在法向上的分量
            # 在药丸外侧、沿走廊方向取样；再扫法向偏移 s
            tally = {}
            for t_sign in (-1, 1):
                # ★ 窗口不能开太宽：线路出了药丸就开始拐弯，取样越远越会被拐弯带偏
                for t in range(int(half) + 12, int(half) + 46, 2):
                    for s_ in range(-130, 131, 1):
                        X = cx + ux * t * t_sign + nx * s_
                        Y = cy + uy * t * t_sign + ny * s_
                        ix, iy = int(round(X)), int(round(Y))
                        if not (0 <= ix < W and 0 <= iy < H):
                            continue
                        c = px[ix, iy]
                        if sum(abs(c[k] - ref[k]) for k in range(3)) < tol:
                            tally[s_] = tally.get(s_, 0) + 1
            if not tally:
                print(f"  line {lid:<3} 数据偏移=({dx:+7.1f},{dy:+7.1f}) 走廊角={ang:6.1f}  -> 原图: 药丸外侧没找到该色")
                continue
            # 取“最大命中簇”的中心（避免别处同色线路误入）
            ks = sorted(tally)
            clusters, cur = [], [ks[0]]
            for k in ks[1:]:
                if k - cur[-1] <= 6:
                    cur.append(k)
                else:
                    clusters.append(cur); cur = [k]
            clusters.append(cur)
            best = max(clusters, key=lambda cl: sum(tally[k] for k in cl))
            tot = sum(tally[k] for k in best)
            mv = sum(k * tally[k] for k in best) / tot
            ok = "OK " if abs(mv - proj) < 13 else "✗ 不一致"
            print(f"  line {lid:<3} 数据偏移=({dx:+7.1f},{dy:+7.1f}) 走廊角={ang:6.1f}  "
                  f"数据法向分量={proj:+7.1f}  原图实测={mv:+7.1f}  命中={tot:5d}  {ok}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["老街", "岗厦北", "深圳北站", "布吉", "车公庙", "光明"]
    main(args)
