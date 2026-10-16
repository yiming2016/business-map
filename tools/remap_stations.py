"""
tools/remap_stations.py
================================
把 OCR 读出来的站名，配对到图上真正的站点标记，从而修正 stations.json 的坐标。

背景：
  之前是靠"人工估坐标 → 就近吸附"来定位站点，结果不少站点被吸附到了
  隔壁站的标记上（例如"老街"的坐标落在"园岭"上）。站名一错位，
  线路连线就会横穿全图，"乱"就是这么来的。

本工具的做法：
  1. 把 OCR 出来的文本与 285 个站名做匹配（先精确、再容错，容忍 1 个错字）；
  2. 每个站名 → 附近若干个候选标记（白底圆点）；
  3. 用代价函数全局贪心配对，代价考虑：
       · 站名文字框到标记中心的距离（越近越好）
       · 标记的长宽比是否与"是否换乘站"吻合（换乘站标记是胶囊形）
       · 标记周围有没有该站所属线路的颜色（线路色不对就说明配错了）
  4. 输出新的坐标；没配上的站点单独列出来人工处理。

用法：
    python tools/remap_stations.py            # 只看报告，不落盘
    python tools/remap_stations.py --apply    # 写回 stations.json（自动备份）
    python tools/remap_stations.py --vis      # 输出核对图 _remap_check.png
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parent.parent
APPLY = "--apply" in sys.argv
VIS = "--vis" in sys.argv

# 图例读出来的官方线路色
LEGEND = {
    "1": (0x00, 0xB0, 0x52), "2": (0xBA, 0x57, 0x00), "3": (0x00, 0xA6, 0xDE),
    "4": (0xD4, 0x2E, 0x12), "5": (0x9E, 0x4D, 0xAB), "6": (0x00, 0xC4, 0xB5),
    "6支": (0x00, 0x8A, 0x80), "7": (0x00, 0x33, 0xAB), "8": (0xBA, 0x57, 0x00),
    "9": (0x8A, 0x6B, 0x70), "10": (0xFC, 0x6C, 0x97), "11": (0x6B, 0x1C, 0x40),
    "12": (0xA8, 0x91, 0xB0), "13": (0xD4, 0x85, 0x00), "14": (0xED, 0xCC, 0x61),
    "16": (0x40, 0x12, 0xA6), "20": (0x99, 0xDB, 0xDE),
    "有轨电车": (0xB6, 0xB6, 0xB7), "坪山云巴": (0xB6, 0xB6, 0xB7),
}
# 原图里同色的线路无法区分，合并成一个"色组"
COLOR_GROUP = {"2": "ORANGE", "8": "ORANGE",
               "有轨电车": "GRAY", "有轨电车支线": "GRAY", "坪山云巴": "GRAY"}

SEARCH_R = 300.0        # 站名文字到标记的最大搜索距离
W_MARKER = 1.0          # 距离权重
W_SHAPE = 90.0          # 形状不符惩罚
W_COLOR = 150.0         # 每缺一条声明线路的颜色惩罚（封顶 2 条）
W_SCORE = 60.0          # OCR 置信度低 → 轻微惩罚


def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def load_image():
    return np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)


def ring_line_colors(img, x, y, r_in=18, r_out=48):
    """标记周围出现过哪些线路色（返回线路 id 集合）。"""
    x, y = int(round(x)), int(round(y))
    y0, y1 = max(0, y - r_out), min(img.shape[0], y + r_out + 1)
    x0, x1 = max(0, x - r_out), min(img.shape[1], x + r_out + 1)
    patch = img[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - y) ** 2 + (xx - x) ** 2
    sel = patch[(d2 >= r_in ** 2) & (d2 <= r_out ** 2)]
    if len(sel) < 50:
        return set()
    found = set()
    for lid, c in LEGEND.items():
        dd = np.abs(sel - np.array(c, dtype=np.int16)).max(axis=1)
        if float((dd <= 46).mean()) > 0.05:
            found.add(COLOR_GROUP.get(lid, lid))
    return found


def main():
    stations = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    labels = json.loads((SRC / "data" / "ocr_labels.json").read_text(encoding="utf-8"))
    markers = json.loads((SRC / "data" / "markers.json").read_text(encoding="utf-8"))["markers"]

    names = list(stations)
    name_set = set(names)

    # 图上这些区域印的是标题/图例，不是站名，直接排除
    def in_annotation(x, y):
        if y > 7180:                       # 底部图例带
            return True
        if y < 700:                        # 顶部标题
            return True
        return False

    # ---------- 1. OCR 文本 → 站名 ----------
    def norm(t: str) -> str:
        return t.replace(" ", "").replace("\u3000", "").replace("站", "").strip()

    norm_map = {}
    for n in names:
        norm_map.setdefault(norm(n), n)

    labels = [lb for lb in labels if not in_annotation(lb["x"], lb["y"])]

    # --- 第一轮：只认精确匹配（最可靠） ---
    matched = []          # (station, label, how)
    used_label_idx = set()
    matched_names = set()
    for i, lb in enumerate(labels):
        t = norm(lb["text"])
        if not t:
            continue
        if t in norm_map:
            sid = norm_map[t]
            matched.append((sid, lb, "exact"))
            used_label_idx.add(i)
            matched_names.add(sid)

    # --- 第二轮：容错匹配，但严格得多 ---
    # 只处理"还没配上的站"，且要求：
    #   · 站名至少 3 个字（两字名容错极易误配，比如 福永/福民/福田）
    #   · 前两个字完全相同
    #   · 只差一个字
    #   · 这个 OCR 文本本身不是别的站名
    fuzzy_cnt = 0
    for i, lb in enumerate(labels):
        if i in used_label_idx:
            continue
        t = norm(lb["text"])
        if len(t) < 3 or t in norm_map:
            continue
        for cand in names:
            if cand in matched_names:
                continue
            nc = norm(cand)
            if len(nc) != len(t) or nc[:2] != t[:2]:
                continue
            if lev(nc, t) <= 1:
                matched.append((cand, lb, "fuzzy"))
                used_label_idx.add(i)
                matched_names.add(cand)
                fuzzy_cnt += 1
                break

    per_station = {}
    for sid, lb, how in matched:
        per_station.setdefault(sid, []).append((lb, how))

    print(f"OCR 命中站名 {len(per_station)} / {len(names)}   （精确 {len(matched) - fuzzy_cnt}，容错 {fuzzy_cnt}）")
    dup = {k: len(v) for k, v in per_station.items() if len(v) > 1}
    if dup:
        print(f"  同名出现在多处（需要消歧）：{dup}")

    img = load_image()

    # ---------- 2. 生成候选与代价 ----------
    def rect_dist(lb, mx, my):
        x0, y0 = lb["x"], lb["y"]
        x1, y1 = lb["x"] + lb["w"], lb["y"] + lb["h"]
        dx = max(x0 - mx, 0.0, mx - x1)
        dy = max(y0 - my, 0.0, my - y1)
        return (dx * dx + dy * dy) ** 0.5

    # 预先算好每个标记的"周围线路色"和形状比
    marker_info = []
    for m in markers:
        mw, mh = float(m["w"]), float(m["h"])
        if min(mw, mh) < 16 or max(mw, mh) > 130:
            continue
        elong = max(mw, mh) / max(min(mw, mh), 1.0)
        area = float(m.get("area") or (mw * mh * float(m.get("fill") or 0.8)))
        # 换乘站标记是胶囊：要么明显拉长，要么明显更大
        is_capsule = (elong > 1.18) or (area > 560)
        marker_info.append({
            "x": float(m["x"]), "y": float(m["y"]),
            "elong": elong, "fill": float(m["fill"]), "area": area,
            "is_capsule": is_capsule,
            "lines": None, "used": False,
        })
    print(f"可用标记候选 {len(marker_info)} 个"
          f"（其中胶囊 {sum(1 for m in marker_info if m['is_capsule'])}）")

    pairs = []
    for sid, lst in per_station.items():
        s = stations[sid]
        want_transfer = bool(s.get("is_transfer"))
        declared = [COLOR_GROUP.get(l, l) for l in (s.get("lines") or [])]
        for lb, how in lst:
            lcx = lb["x"] + lb["w"] / 2
            lcy = lb["y"] + lb["h"] / 2
            for mi, m in enumerate(marker_info):
                d = rect_dist(lb, m["x"], m["y"])
                if d > SEARCH_R:
                    continue
                cost = W_MARKER * d
                # 换乘站标记是胶囊（长宽比大）
                if want_transfer != m["is_capsule"]:
                    cost += W_SHAPE
                cost += W_SCORE * (1.0 - lb["score"])
                pairs.append([cost, sid, mi, lb, d])
            _ = lcx, lcy

    # 线路色核查（只对可能入选的标记算，省时间）
    need = set(p[2] for p in pairs)
    for mi in need:
        m = marker_info[mi]
        m["lines"] = ring_line_colors(img, m["x"], m["y"])

    # 反过来：周边颜色完全不沾边 → 加惩罚
    for p in pairs:
        m = marker_info[p[2]]
        declared = [COLOR_GROUP.get(x, x) for x in (stations[p[1]].get("lines") or [])]
        hit = len(set(declared) & (m["lines"] or set()))
        miss = len(set(declared)) - hit
        p[0] += W_COLOR * min(miss, 2)

    pairs.sort(key=lambda p: p[0])

    assigned = {}
    for cost, sid, mi, lb, d in pairs:
        if sid in assigned or marker_info[mi]["used"]:
            continue
        assigned[sid] = (marker_info[mi]["x"], marker_info[mi]["y"], cost, d, mi)
        marker_info[mi]["used"] = True

    print(f"配对成功 {len(assigned)} / {len(names)}")

    # ---------- 3. 兜底：靠线路站序补齐 OCR 没读到的站 ----------
    # 思路：某条线路上 A - X - B，若 A、B 都已定位，而 X 没有，
    #       那么 X 的标记应该落在 A、B 之间；在中间找一个"还没被占用的标记"即可。
    missing = [n for n in names if n not in assigned]
    if missing:
        lines = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))["lines"]
        added = []
        for _round in range(4):
            progress = False
            for ln in lines:
                seq = ln.get("stations") or []
                for i, sid in enumerate(seq):
                    if sid not in missing:
                        continue
                    near = []
                    for j in range(i - 1, -1, -1):
                        if seq[j] in assigned:
                            near.append(assigned[seq[j]][:2]); break
                    for j in range(i + 1, len(seq)):
                        if seq[j] in assigned:
                            near.append(assigned[seq[j]][:2]); break
                    if not near:
                        continue
                    if len(near) == 2:
                        cx = (near[0][0] + near[1][0]) / 2
                        cy = (near[0][1] + near[1][1]) / 2
                        span = ((near[0][0] - near[1][0]) ** 2 + (near[0][1] - near[1][1]) ** 2) ** 0.5
                        limit = max(260.0, span * 0.75)
                    else:
                        cx, cy = near[0]
                        limit = 700.0
                    declared = [COLOR_GROUP.get(l, l) for l in (stations[sid].get("lines") or [])]
                    best = None
                    for mi, m in enumerate(marker_info):
                        if m["used"]:
                            continue
                        dd = ((m["x"] - cx) ** 2 + (m["y"] - cy) ** 2) ** 0.5
                        if dd > limit:
                            continue
                        miss = len(set(declared)) - len(set(declared) & (m["lines"] or set()))
                        c = dd + W_COLOR * min(miss, 2)
                        if best is None or c < best[0]:
                            best = (c, mi, dd)
                    if best is None:
                        continue
                    _c, mi, dd = best
                    assigned[sid] = (marker_info[mi]["x"], marker_info[mi]["y"], _c, dd, mi)
                    marker_info[mi]["used"] = True
                    missing.remove(sid)
                    added.append((sid, round(dd)))
                    progress = True
            if not progress:
                break
        if added:
            print(f"兜底补位 {len(added)} 个：{added}")

    # ---------- 4. 报告 ----------
    dists = [v[3] for v in assigned.values()]
    if dists:
        dists.sort()
        print(f"文字到标记的距离：中位 {dists[len(dists)//2]:.0f}px  "
              f"最大 {dists[-1]:.0f}px")

    moved = []
    for sid, (nx, ny, cost, d, mi) in assigned.items():
        s = stations[sid]
        od = ((s["x"] - nx) ** 2 + (s["y"] - ny) ** 2) ** 0.5
        moved.append((od, sid, s["x"], s["y"], nx, ny))
    moved.sort(reverse=True)
    print("\n位移最大的 12 个站点（说明之前确实配错了）：")
    for od, sid, ox, oy, nx, ny in moved[:12]:
        print(f"  {sid:<8} ({ox:>7.1f},{oy:>7.1f}) → ({nx:>7.1f},{ny:>7.1f})   移动 {od:>7.1f}px")

    missing = [n for n in names if n not in assigned]
    print(f"\n未能配对的站点 {len(missing)} 个：")
    if missing:
        print("  " + "、".join(missing))

    # ---------- 5. 核对图 ----------
    if VIS:
        base = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
        base = base.resize((base.width // 4, base.height // 4), Image.LANCZOS)
        dr = ImageDraw.Draw(base)
        sc = 0.25
        for sid, (nx, ny, *_rest) in assigned.items():
            s = stations[sid]
            dr.line([s["x"] * sc, s["y"] * sc, nx * sc, ny * sc], fill=(255, 0, 0), width=1)
            dr.ellipse([nx * sc - 4, ny * sc - 4, nx * sc + 4, ny * sc + 4], outline=(0, 160, 0), width=2)
        for n in missing:
            s = stations[n]
            dr.ellipse([s["x"] * sc - 5, s["y"] * sc - 5, s["x"] * sc + 5, s["y"] * sc + 5],
                       outline=(0, 0, 255), width=2)
        out = SRC / "_remap_check.png"
        base.save(out)
        print(f"核对图 → {out}（绿圈=新坐标，红点=旧坐标，蓝圈=未能配对）")

    # ---------- 6. 落盘 ----------
    if APPLY:
        ts = datetime.now().strftime("%m%d%H%M")
        for n in ("stations.json",):
            src = SRC / "data" / n
            shutil.copy2(src, SRC / "data" / f"{n}.bak_remap_{ts}")
        for sid, (nx, ny, *_rest) in assigned.items():
            stations[sid]["x"] = round(nx, 1)
            stations[sid]["y"] = round(ny, 1)
        p = SRC / "data" / "stations.json"
        p.write_text(json.dumps({"version": "2.0",
                                 "description": "站点数据。x/y 为原图像素坐标。",
                                 "stations": stations},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[OK] 已写回 {p}（备份 .bak_remap_{ts}），修正 {len(assigned)} 个站点坐标")


if __name__ == "__main__":
    main()
