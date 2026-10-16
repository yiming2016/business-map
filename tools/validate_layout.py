"""
tools/validate_layout.py
================================
客观校验：我们画的线，到底跟原图重合多少？

做法：
  对每条线路的每一对"相邻站"，在两点连线上均匀取样，看每个取样点附近
  有没有该线路的颜色。覆盖率高的说明这两站确实相邻；接近 0 的说明配错了、
  或者顺序排错了。

同时也检八向折线版本（原图是横/竖/45° 画法，直连取样会低估）。

用法：
    python tools/validate_layout.py            # 总览
    python tools/validate_layout.py -v         # 列出最差的 30 段
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
VERBOSE = "-v" in sys.argv

LEGEND = {
    "1": (0x00, 0xB0, 0x52), "2": (0xBA, 0x57, 0x00), "3": (0x00, 0xA6, 0xDE),
    "4": (0xD4, 0x2E, 0x12), "5": (0x9E, 0x4D, 0xAB), "6": (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7": (0x00, 0x33, 0xAB), "8": (0xBA, 0x57, 0x00),
    "9": (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
    "有轨电车": (0xB6, 0xB6, 0xB7), "有轨电车支线": (0xB6, 0xB6, 0xB7),
    "坪山云巴": (0xB6, 0xB6, 0xB7),
}
TOL = 58          # 颜色容差
WIN = 9           # 取样点周围搜索窗口半径


def main():
    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    stations = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lines = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))["lines"]

    def cover(a, b, col):
        """a,b 为 (x,y)。在连线上取样，返回"附近有该颜色"的比例。"""
        ax, ay = a; bx, by = b
        n = max(12, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 / 18))
        ts = np.linspace(0.06, 0.94, n)
        xs = (ax + (bx - ax) * ts).astype(int)
        ys = (ay + (by - ay) * ts).astype(int)
        ok = 0
        for x, y in zip(xs, ys):
            x0, x1 = max(0, x - WIN), min(W, x + WIN + 1)
            y0, y1 = max(0, y - WIN), min(H, y + WIN + 1)
            patch = img[y0:y1, x0:x1]
            dd = np.abs(patch - np.array(col, dtype=np.int16)).max(axis=2)
            if (dd <= TOL).any():
                ok += 1
        return ok / n

    seg_rows = []
    print(f"{'线路':<5}{'段数':>5}{'直连覆盖':>10}{'八向覆盖':>10}   最差段")
    print("-" * 76)
    for ln in lines:
        lid = ln["id"]
        col = LEGEND.get(lid) or LEGEND.get(lid.replace("支", ""))
        if col is None:
            continue
        seq = [s for s in (ln.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        direct = []
        octi = []
        for i in range(1, len(seq)):
            a = (stations[seq[i - 1]]["x"], stations[seq[i - 1]]["y"])
            b = (stations[seq[i]]["x"], stations[seq[i]]["y"])
            c1 = cover(a, b, col)
            direct.append(c1)
            # 八向：先 45° 再直
            dx, dy = b[0] - a[0], b[1] - a[1]
            adx, ady = abs(dx), abs(dy)
            if min(adx, ady) > 30 and abs(adx - ady) > max(adx, ady) * 0.16:
                m = min(adx, ady)
                mid = (a[0] + (m if dx > 0 else -m), a[1] + (m if dy > 0 else -m))
                c2 = (cover(a, mid, col) + cover(mid, b, col)) / 2
            else:
                c2 = c1
            octi.append(c2)
            seg_rows.append((min(c1, c2), c1, c2, lid, seq[i - 1], seq[i],
                             ((dx * dx + dy * dy) ** 0.5)))
        worst = min(direct)
        wi = direct.index(worst)
        print(f"{lid:<5}{len(seq)-1:>5}{np.mean(direct):>9.1%}{np.mean(octi):>10.1%}"
              f"   {seq[wi]}→{seq[wi+1]} ({worst:.0%})")

    seg_rows.sort()
    allc = [r[0] for r in seg_rows]
    print("-" * 76)
    print(f"全部 {len(seg_rows)} 段：平均 {np.mean(allc):.1%}  中位 {np.median(allc):.1%}"
          f"  <40% 的段共 {sum(1 for c in allc if c < 0.4)} 段")

    if VERBOSE:
        print("\n最差的 30 段：")
        for c, c1, c2, lid, a, b, d in seg_rows[:30]:
            print(f"  {lid:>4}号线 {a:<8}→{b:<8} 覆盖 {c1:>5.0%}/{c2:>5.0%}  长度 {d:>7.0f}px")


if __name__ == "__main__":
    main()
