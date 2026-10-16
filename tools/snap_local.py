"""保守的局部吸附：只把"明显没落在任何标记上"的站点挪到邻近的空闲标记上。

为什么不沿用全局贪心配对（tools/remap_stations.py）：
  站点数涨到 320 之后，全局最小代价会为了省一点点总代价，把本来正确的站点
  大范围搬走（实测把「海上世界」搬了 1200px、「后海」搬了 885px）。
  所以改成两段式、带守卫的局部吸附：

  第一段：距离 45px 内已有标记 -> 直接对齐到标记中心（可信）
  第二段：没有标记的站 -> 在 130px 内找"空闲 + 环色与声明线路相符"的标记；
          候选不唯一就不动，只报告。

用法:
  python tools/snap_local.py           # 只报告
  python tools/snap_local.py --apply   # 写回（自动备份）
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

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
GROUP = {"2": "ORANGE", "8": "ORANGE",
         "有轨电车": "GRAY", "有轨电车支线": "GRAY", "坪山云巴": "GRAY"}

STAGE1 = 45.0
STAGE2 = 60.0
COLOR_TOL = 26


def ring_colors(img, x, y, mw, mh):
    """标记周围（环形带）出现过的线色组。"""
    r_in = max(mw, mh) / 2.0 + 2.0
    r_out = r_in + 16.0
    x, y = int(round(x)), int(round(y))
    y0, y1 = max(0, int(y - r_out)), min(img.shape[0], int(y + r_out) + 1)
    x0, x1 = max(0, int(x - r_out)), min(img.shape[1], int(x + r_out) + 1)
    patch = img[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - y) ** 2 + (xx - x) ** 2
    sel = patch[(d2 >= r_in ** 2) & (d2 <= r_out ** 2)]
    if len(sel) < 40:
        return set()
    out = set()
    for lid, c in LEGEND.items():
        dd = np.abs(sel - np.array(c, dtype=np.int16)).max(axis=1)
        if float((dd <= COLOR_TOL).mean()) > 0.12:
            out.add(GROUP.get(lid, lid))
    return out


def main():
    apply = "--apply" in sys.argv
    S = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))["stations"]
    markers = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    img = np.asarray(Image.open(IMG).convert("RGB")).astype(np.int16)

    M = [dict(m, used=False, owner=None) for m in markers]

    def nearest(x, y, r):
        best, bd = None, 1e18
        for i, m in enumerate(M):
            d = ((m["x"] - x) ** 2 + (m["y"] - y) ** 2) ** 0.5
            if d < bd:
                bd, best = d, i
        if best is not None and bd <= r:
            return best, bd
        return None, bd

    # ---------- 第一段 ----------
    snapped1, conflicts = [], []
    order = sorted(S.values(), key=lambda s: nearest(s["x"], s["y"], STAGE1)[1])
    for s in order:
        i, d = nearest(s["x"], s["y"], STAGE1)
        if i is None:
            continue
        m = M[i]
        if m["used"]:
            conflicts.append((s["station_id"], m["owner"], round(d, 1)))
            continue
        m["used"] = True
        m["owner"] = s["station_id"]
        if d > 3:
            snapped1.append((s["station_id"], round(s["x"], 1), round(s["y"], 1),
                             m["x"], m["y"], round(d, 1)))

    # ---------- 第二段 ----------
    fallback, still_off = [], []
    for s in S.values():
        i, d = nearest(s["x"], s["y"], STAGE1)
        if i is not None:
            continue
        want = {GROUP.get(l, l) for l in (s.get("lines") or [])}
        cands = []
        for j, m in enumerate(M):
            if m["used"]:
                continue
            dd = ((m["x"] - s["x"]) ** 2 + (m["y"] - s["y"]) ** 2) ** 0.5
            if dd > STAGE2:
                continue
            rc = ring_colors(img, m["x"], m["y"], m["w"], m["h"])
            if not (want & rc):
                continue
            cands.append((dd, j, m))
        if len(cands) == 1:
            dd, j, m = cands[0]
            m["used"] = True
            m["owner"] = s["station_id"]
            fallback.append((s["station_id"], round(s["x"], 1), round(s["y"], 1),
                             m["x"], m["y"], round(dd, 1)))
        else:
            still_off.append((s["station_id"], round(s["x"], 1), round(s["y"], 1),
                              len(cands), round(d, 1)))

    print(f"第一段（贴标记对齐）: {len(snapped1)} 个需要微调")
    for sid, ox, oy, nx, ny, d in sorted(snapped1, key=lambda r: -r[5])[:20]:
        print(f"   {sid:<8s} ({ox:>7.1f},{oy:>7.1f}) -> ({nx:>7.1f},{ny:>7.1f})   {d:>6.1f}px")
    if conflicts:
        print(f"\n标记被两站争抢 {len(conflicts)} 处：")
        for sid, owner, d in conflicts:
            print(f"   {sid} 与 {owner} 争同一标记（距 {d}px）")

    print(f"\n第二段（就近吸附到空闲标记）: {len(fallback)} 个")
    for sid, ox, oy, nx, ny, d in sorted(fallback, key=lambda r: -r[5]):
        print(f"   {sid:<10s} ({ox:>7.1f},{oy:>7.1f}) -> ({nx:>7.1f},{ny:>7.1f})   {d:>6.1f}px")

    print(f"\n仍无匹配标记 {len(still_off)} 个（附图或人工布点的站属正常）：")
    for sid, x, y, n, d in sorted(still_off, key=lambda r: -r[3]):
        print(f"   {sid:<10s} ({x:>7.1f},{y:>7.1f})  候选{n}个  最近{d:.0f}px")

    if apply:
        ts = datetime.now().strftime("%m%d%H%M")
        f = DATA / "stations.json"
        shutil.copy2(f, DATA / f"stations.json.bak_snap_{ts}")
        for sid, ox, oy, nx, ny, d in snapped1:
            S[sid]["x"], S[sid]["y"] = nx, ny
        for sid, ox, oy, nx, ny, d in fallback:
            S[sid]["x"], S[sid]["y"] = nx, ny
        f.write_text(json.dumps({"version": "2.3",
                                 "description": "站点数据。x/y 为原图像素坐标（原图 8000x8000）。",
                                 "stations": S}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[OK] 已写回 {f}（备份 .bak_snap_{ts}）：微调 {len(snapped1)}，吸附 {len(fallback)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
