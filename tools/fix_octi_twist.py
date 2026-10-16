# -*- coding: utf-8 -*-
"""修「奇怪的扭曲」：官方是**平滑弧**的段被八向化切成了台阶。

用户原话：「很多地方都有奇怪的扭曲，根本无法修复，你来自动探测并修复」。
截图那处是 13 号线 **光明城 → 德雅路**：

    官方原图在这一段是一条**向右鼓的连续弧**（每 25px 的 x 中位：
    2521 → 2543 → 2589 → 2612 → **2614**(y=2035) → 2604 → 2588 → 2535 → 2492），
    也就是平滑地鼓出 ~120px 再收回来。

    而 v2.6.61 起「描线边也走八向化」⇒ 这段被拆成
        …(2614,2031) --45°斜线--> (2523,1940) --36px 短竖线--> (2523,1904)
    一个 135° 的尖折 + 一条比线宽(22px)长不了多少的短边，再叠上圆角倒角
    ⇒ 屏幕上看就是个扭曲的月牙（截图里那条浅色弧）。

判据（只认官方像素，不认我自己的画法）：
    对每一段，分别取「八向化后」和「原样」两条路径，量各自离**官方同色像素**
    的距离 p90（两端各去掉 15% 的采样点，避开站点图标盖住的地方）。
    「原样」明显更贴（> BETTER px）⇒ 这一段**不该八向化**。

用法：
    python tools/fix_octi_twist.py            # 只看不动（打统计 + 最差的 30 段）
    python tools/fix_octi_twist.py --apply    # 写入 lines.json["octi_off"]（先备份）
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
DATA = ROOT.parent / "软件" / "data"
COLORS = json.loads((ROOT / "_tmp_official_colors.json").read_text(encoding="utf-8"))
OFF = np.asarray(Image.open(ROOT / "assets" / "shenzhen_metro.png").convert("RGB")
                 ).astype(np.int16)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import core.data_manager as CDM                      # noqa: E402

CDM.DATA_DIR = DATA
CDM.STATIONS_FILE = DATA / "stations.json"
CDM.LINES_FILE = DATA / "lines.json"

from ui.map_view import build_line_points_ex        # noqa: E402
from ui import metro_render as MR                   # noqa: E402

TOL = 48
EDGE_TRIM = 0.15      # 两端各去掉 15% 的采样点（站点图标把走廊盖住了）
BETTER = 3.0          # 「原样」比「八向化」至少好这么多像素，才判"不该八向化"
SAMPLE = 12.0         # 沿折线的采样步长
# ★★ 官方原图里**几条线用同一个颜色**（2↔8、4↔10↔有轨电车、16↔坪山云巴）
#   ⇒ 按颜色取掩膜会串线，"谁更贴某条同色线"这个判据对它们**不可靠**。
#   对这几条线加严：必须"原样紧贴某条线(<12px) 且 八向化明显跑开(>18px)"才动。
#   （实测 4/2/10 的候选段 d_raw 都 ≥15.8px ⇒ 一律不动，保守优先。）
SAME_COLOR = {"2", "8", "4", "10", "16", "有轨电车", "有轨电车支线", "坪山云巴"}
SAME_RAW_MAX = 12.0
SAME_OCTI_MIN = 18.0


def rgb_of(lid):
    """`_tmp_official_colors.json` 的结构是 {线号: {"name":…, "colors": [[rgb, n], …]}}。

    取**主色**即可：后面的都是主色的抗锯齿变体，跟主色距离 < TOL，会被掩膜一起收进来。
    """
    e = COLORS.get(str(lid))
    if not e:
        return None
    if isinstance(e, dict):
        cs = e.get("colors") or []
        return cs[0][0] if cs else None
    return e


def official_tree(rgb):
    d = np.abs(OFF - np.array(rgb, dtype=np.int16)).sum(axis=2)
    ys, xs = np.nonzero(d < TOL)
    return cKDTree(np.column_stack([xs, ys]).astype(float))


def resample(pts, step=SAMPLE):
    P = [(float(p[0]), float(p[1])) for p in pts]
    if len(P) < 2:
        return np.zeros((0, 2))
    out = []
    for i in range(len(P) - 1):
        x0, y0 = P[i]
        x1, y1 = P[i + 1]
        L = float(np.hypot(x1 - x0, y1 - y0))
        n = max(1, int(np.ceil(L / step)))
        for k in range(n):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    out.append(P[-1])
    return np.asarray(out, dtype=float)


def dev(tree, pts):
    """折线离官方同色像素的 p90（去掉两端各 EDGE_TRIM）。"""
    P = resample(pts)
    if len(P) < 8:
        return None
    k = int(len(P) * EDGE_TRIM)
    if len(P) - 2 * k >= 4:
        P = P[k:len(P) - k]
    d, _ = tree.query(P)
    return float(np.percentile(d, 90))


def main():
    apply = "--apply" in sys.argv
    dm = CDM.get_data_manager()
    st = dm.all_stations()
    doc = dm.lines_doc
    traced = doc.get("traced") or {}
    trees = {}
    rows = []
    missing_color = set()

    for L in (doc.get("lines") or []):
        lid = str(L.get("id"))
        rgb = rgb_of(lid)
        if not rgb:
            missing_color.add(lid)
            continue
        if lid not in trees:
            trees[lid] = official_tree(rgb)
        tree = trees[lid]
        seq = [n for n in (L.get("stations") or []) if n in st]
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            key = "%s|%s|%s" % (lid, a, b)
            pts, ebl = build_line_points_ex(lid, [a, b], st)
            if len(pts) < 2:
                continue
            raw = [(p.x(), p.y()) for p in pts]
            w = MR.octilinear_waypoints_tagged(pts, ebl)
            octi = [(p.x(), p.y()) for p, _s in w]
            if len(octi) == len(raw):
                continue                      # 八向化什么都没加 ⇒ 无所谓
            d_raw = dev(tree, raw)
            d_octi = dev(tree, octi)
            if d_raw is None or d_octi is None:
                continue
            rows.append({
                "key": key, "lid": lid, "a": a, "b": b,
                "d_raw": d_raw, "d_octi": d_octi,
                "gain": d_octi - d_raw,
                "n_raw": len(raw), "n_octi": len(octi),
                "traced": key in traced,
            })

    def accept(r):
        if r["gain"] <= BETTER:
            return False
        if r["lid"] in SAME_COLOR:      # 同色线：只认"原样紧贴、八向化明显跑开"
            return r["d_raw"] < SAME_RAW_MAX and r["d_octi"] > SAME_OCTI_MIN
        return True

    rows.sort(key=lambda r: -r["gain"])
    fixed = [r for r in rows if accept(r)]
    held = [r for r in rows if r["gain"] > BETTER and not accept(r)]
    print("=" * 96)
    print("八向化 vs 原样（离官方同色像素的 p90，越小越贴底图）")
    print("=" * 96)
    print("共审 %d 段（八向化加了点的那些），其中 traced %d 段"
          % (len(rows), sum(1 for r in rows if r["traced"])))
    print("「原样」更贴 > %.1fpx 的段：%d 段" % (BETTER, len(fixed)))
    print("「八向化」更贴 > %.1fpx 的段：%d 段（这些保持现状）"
          % (BETTER, sum(1 for r in rows if r["gain"] < -BETTER)))
    if fixed:
        g = np.array([r["gain"] for r in fixed])
        print("改善幅度：中位 %.1fpx，最大 %.1fpx" % (float(np.median(g)), float(g.max())))
    if held:
        print("同色冲突、暂不动：%d 段（%s）"
              % (len(held), "、".join(sorted({r["key"] for r in held}))[:120]))
    if missing_color:
        print("没有官方色、跳过：%s" % "、".join(sorted(missing_color)))
    print("-" * 96)
    print("%-30s %-9s %-9s %-8s %s" % ("段", "八向化后", "原样", "改善", "点数"))
    for r in rows[:30]:
        print("%-30s %8.1f  %8.1f  %+7.1f  %d→%d%s"
              % (r["key"], r["d_octi"], r["d_raw"], r["gain"],
                 r["n_octi"], r["n_raw"], "  ★描线" if r["traced"] else ""))

    if not apply:
        print("\n（只看不动；要写入请加 --apply）")
        return 0

    if not fixed:
        print("\n没有需要改的段。")
        return 0

    bak = DATA / ("lines.json.bak_octi_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(DATA / "lines.json", bak)
    # ★★ 名单必须**累积**：已经在名单里的段，因为改完之后"八向化不再加点"，
    #    就不会再出现在这一轮的 fixed 里 —— 直接覆盖会把它们踢出去、打回原形
    #    （实测第二轮只剩 7 段，覆盖后就只剩 7 段了）。
    keys = sorted(set(doc.get("octi_off") or []) | {r["key"] for r in fixed})
    doc["octi_off"] = keys
    tmp = DATA / "lines.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA / "lines.json")
    print("\n[OK] 已写入 octi_off：%d 段（备份 %s）" % (len(keys), bak.name))
    for k in keys[:15]:
        print("     ", k)
    if len(keys) > 15:
        print("      ……")
    return 0


if __name__ == "__main__":
    sys.exit(main())
