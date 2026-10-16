# -*- coding: utf-8 -*-
"""★★★ 已作废，别再用！留作教训（2026-10-01 v2.6.58）★★★

实测：应用后**全线变差**（1号线 P90 21→30、11号线 71→81、2号线 17→36），已回滚。
原因：**路径点本来就 med 0.5px、已经压在官方线上**，再去挪站点只会把它推离中心线
（"官方色最近像素" ≠ 线的中心线，还可能是边缘/别的同色东西）。
真正的病是**"段的走法不对"**（官方带拐弯、我是两站直连），跟站点位置无关。
⇒ 要修请改 `lines_doc["traced"]`（逐段重建走法），不要动 stations。

---- 下面是原始说明（结论已作废）----
把站点**吸附回官方原图上的线**（可靠判据：官方原图的线色）。

原理：我的线路是"站点连出来的" ⇒ 线路偏 = 站点偏。
     所以修线路的办法是**把站点拉回官方线**，而不是去改画线算法。

★ 只做**横向修正**：最近点 ≈ 垂足，纵向(沿线)位置基本不变，
  所以站与站的先后顺序、站距不会被打乱。

★ 三重保护（都是被坑出来的）：
  ① 只在站点附近 ±SEARCH 内找官方色像素 ⇒ 图例/别处的同色线不会污染；
  ② 移动量超过 MAX_MOVE 的一律不动（判定为"附近根本没有这条线"，多半是提取失败）；
  ③ 换乘站多条线各给一个候选 ⇒ 候选彼此差超过 SPLIT 就**不动**
     （记忆里的坑：两条线走廊不相交时取平均 ⇒ 落到无人区被求解器甩飞）。

用法：
    python tools/fix_snap_to_official.py            # 只报告，不写
    python tools/fix_snap_to_official.py --apply    # 真的写（会先备份）
"""
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT.parent / "软件" / "data"

SEARCH = 150.0      # 只在站点附近这么大范围内找官方色像素
MAX_MOVE = 130.0    # 单站最多移动这么多
SPLIT = 90.0        # 换乘站各线候选彼此分歧超过这个 ⇒ 放弃（不动）

ST_F = DATA / "stations.json"
LINES_F = DATA / "lines.json"
ST = json.loads(ST_F.read_text(encoding="utf-8"))["stations"]
LINES = json.loads(LINES_F.read_text(encoding="utf-8"))["lines"]
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)

# 同色的线会互相干扰，跳过（2↔8、4↔10↔有轨电车、16↔坪山云巴）
SKIP = {"10", "有轨电车", "坪山云巴", "8", "4", "16", "2", "有轨电车支线"}


def local_mask(rgb, cx, cy, r=SEARCH, tol=48):
    """只取站点附近 ±r 范围内的官方色像素"""
    x0, y0 = max(0, int(cx - r)), max(0, int(cy - r))
    x1, y1 = min(8000, int(cx + r)), min(8000, int(cy + r))
    if x1 <= x0 or y1 <= y0:
        return None
    blk = OFF[y0:y1, x0:x1]
    d = np.abs(blk - np.array(rgb, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d < tol)
    if len(xs) < 30:
        return None
    return np.column_stack([xs + x0, ys + y0]).astype(float)


def collect():
    """给每个站收集"该拉到哪"的候选（来自它所属的每一条线）"""
    cand = {}
    for l in LINES:
        lid = str(l.get("id"))
        if lid in SKIP:
            continue
        cols = (COLORS.get(lid) or {}).get("colors") or []
        if not cols:
            continue
        rgb = cols[0][0]
        seq = [s for s in (l.get("stations") or []) if s in ST and ST[s].get("x") is not None]
        for s in seq:
            v = ST[s]
            cx, cy = float(v["x"]), float(v["y"])
            M = local_mask(rgb, cx, cy)
            if M is None:
                continue
            dd = np.hypot(M[:, 0] - cx, M[:, 1] - cy)
            j = int(dd.argmin())
            if dd[j] > MAX_MOVE:
                continue
            cand.setdefault(s, []).append((M[j, 0], M[j, 1], lid))
    return cand


def resolve(cand):
    """把候选定成一个新位置；分歧太大就放弃"""
    plan, skip = {}, {}
    for s, cs in cand.items():
        P = np.array([[c[0], c[1]] for c in cs], float)
        v = ST[s]
        cur = np.array([float(v["x"]), float(v["y"])], float)
        nline = len({c[2] for c in cs})
        if nline >= 2:
            spread = float(np.max(np.linalg.norm(P - P.mean(axis=0), axis=1)))
            if spread > SPLIT:
                skip[s] = ("换乘站各线走廊分歧 %.0fpx > %.0f，不敢动" % (spread, SPLIT), cs)
                continue
        new = P.mean(axis=0)
        move = float(np.hypot(*(new - cur)))
        plan[s] = (float(new[0]), float(new[1]), move, [c[2] for c in cs])
    return plan, skip


def main():
    cand = collect()
    plan, skip = resolve(cand)
    moves = sorted(plan.values(), key=lambda r: -r[2])
    print("=" * 92)
    print("站点吸附到官方线 —— %s" % ("**写入模式**" if "--apply" in sys.argv else "只看不动（加 --apply 才写）"))
    print("=" * 92)
    print("有候选的站 %d 个 ｜ 因换乘分歧放弃 %d 个 ｜ 全库 %d 站"
          % (len(plan), len(skip), len(ST)))
    if moves:
        print("移动量：中位 %.1fpx ｜ 最大 %.1fpx ｜ >60px 的 %d 个 ｜ >30px 的 %d 个"
              % (np.median([m[2] for m in moves]), moves[0][2],
                 len([m for m in moves if m[2] > 60]), len([m for m in moves if m[2] > 30])))
    print()
    print("移动最大的 20 个站：")
    for s, (x, y, mv, lids) in sorted(plan.items(), key=lambda kv: -kv[1][2])[:20]:
        v = ST[s]
        print("   %-10s (%.0f,%.0f) → (%.0f,%.0f)  移 %5.1fpx  线%s"
              % (s, v["x"], v["y"], x, y, mv, "/".join(lids)))
    if skip:
        print()
        print("放弃的换乘站（前 10 个）：")
        for s, (why, cs) in list(skip.items())[:10]:
            print("   %-10s %s（候选来自 %s）" % (s, why, "/".join(c[2] for c in cs)))

    if "--apply" not in sys.argv:
        print()
        print("（没写入。确认无误后加 --apply）")
        return 0

    bak = DATA / ("stations.json.bak_snap_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(ST_F, bak)
    print()
    print("[备份] %s" % bak.name)
    n = 0
    for s, (x, y, mv, _l) in plan.items():
        ST[s]["x"] = round(x, 1)
        ST[s]["y"] = round(y, 1)
        n += 1
    ST_F.write_text(json.dumps({"stations": ST}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[写入] 移动了 %d 个站" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
