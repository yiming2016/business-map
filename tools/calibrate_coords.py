"""
tools/calibrate_coords.py
========================
坐标校准：把站点吸附到图上「该线路颜色」的最近像素。

原理：
  1. 读入 8000x8000 底图，降采样到 2000x2000（速度/内存友好）
  2. 每条线路按"图上实际色"生成颜色蒙版（float32 计算，避免 int16 溢出）
  3. 连通域分析：剔除「大片实心色块」（通常是背景/水域/图例），只保留细长线条
  4. 站点在现有坐标附近限定半径内搜索最近线条像素
  5. 位移超过上限 → 放弃吸附，保留原值（保证不劣化）
  6. 避免多站吸到同一像素

用法：
    python tools/calibrate_coords.py --dry-run
    python tools/calibrate_coords.py
    python tools/calibrate_coords.py --skip-lines 6,20,12,9 --max-move 90
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

try:
    from scipy import ndimage
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

SRC_ROOT = Path(__file__).resolve().parent.parent
IMG_PATH = SRC_ROOT / "assets" / "shenzhen_metro.png"
STATIONS_PATH = SRC_ROOT / "data" / "stations.json"

SCALE = 4
WORK = 8000 // SCALE

# 图上实际呈现的线路色
LINE_ACTUAL_COLOR = {
    "1":  (0x08, 0xB8, 0x48),
    "2":  (0xE8, 0x88, 0x08),
    "3":  (0x08, 0x98, 0xC8),
    "4":  (0xE8, 0x28, 0x38),
    "5":  (0xF8, 0x18, 0x18),
    "6":  (0x08, 0xB8, 0xA8),
    "7":  (0x08, 0x48, 0xB8),
    "8":  (0xE8, 0x08, 0x18),
    "9":  (0xB8, 0x98, 0x18),
    "10": (0xD8, 0x78, 0x08),
    "11": (0xB8, 0x18, 0x28),
    "12": (0xC8, 0xA8, 0x58),
    "13": (0xE8, 0x88, 0x08),
    "14": (0xF8, 0xB8, 0x18),
    "16": (0x98, 0x78, 0xC8),
    "20": (0xC8, 0xD8, 0xE8),
}


def build_mask(arr_f: np.ndarray, rgb, tol: float) -> np.ndarray:
    """生成颜色蒙版。arr_f 为 float32。"""
    target = np.array(rgb, dtype=np.float32)
    diff = arr_f - target
    dist = np.sqrt((diff * diff).sum(axis=2))
    return dist <= tol


def clean_mask(mask: np.ndarray, max_blob_area: int = 12000, min_compactness_filter: float = 0.45):
    """
    去掉「大片实心色块」，保留细长线条。

    判据：某个连通域若「面积/外接框面积」> min_compactness_filter 且面积较大，
    则认为是色块（背景/水域/图例），剔除。
    """
    if not HAS_SCIPY:
        return mask
    lab, n = ndimage.label(mask)
    if n == 0:
        return mask
    keep = np.zeros(n + 1, dtype=bool)
    objects = ndimage.find_objects(lab)
    for i, sl in enumerate(objects, start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        area = int((lab[sl] == i).sum())
        bbox = max(h * w, 1)
        compact = area / bbox
        is_blob = (area > max_blob_area) and (compact > min_compactness_filter)
        keep[i] = not is_blob
    out = keep[lab]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tolerance", type=float, default=42.0)
    ap.add_argument("--radius", type=float, default=100.0, help="搜索半径（2000 尺度）")
    ap.add_argument("--max-move", type=float, default=95.0, help="最大允许位移（2000 尺度）")
    ap.add_argument("--skip-lines", type=str, default="", help="跳过的线路 id，逗号分隔")
    args = ap.parse_args()

    skip = set(x.strip() for x in args.skip_lines.split(",") if x.strip())
    if skip:
        print(f"跳过校准的线路: {sorted(skip)}")

    print(f"载入 {IMG_PATH.name} ...")
    img = Image.open(IMG_PATH).convert("RGB").resize((WORK, WORK), Image.BILINEAR)
    arr_f = np.asarray(img).astype(np.float32)

    with open(STATIONS_PATH, "r", encoding="utf-8") as f:
        doc = json.load(f)
    stations = doc["stations"]

    # 生成蒙版
    masks = {}
    for lid, rgb in LINE_ACTUAL_COLOR.items():
        m = build_mask(arr_f, rgb, args.tolerance)
        raw = int(m.sum())
        m2 = clean_mask(m)
        masks[lid] = m2
        print(f"  线路{lid:>2} 原始 {raw:>7} → 清洗后 {int(m2.sum()):>7}")

    used = set()
    moved = kept = 0
    details = []

    ordered = sorted(stations.values(), key=lambda s: (-len(s.get("lines", [])), s["station_name"]))

    for st in ordered:
        name = st["station_name"]
        ox, oy = st["x"] / SCALE, st["y"] / SCALE
        lines = [l for l in st.get("lines", []) if l not in skip]

        if not lines:
            kept += 1
            used.add((int(round(ox)), int(round(oy))))
            details.append((name, "跳过", (round(ox * SCALE), round(oy * SCALE)), None, None))
            continue

        best = None
        best_d = 1e9
        for lid in lines:
            mask = masks.get(lid)
            if mask is None:
                continue
            x0 = max(0, int(ox - args.radius)); x1 = min(WORK, int(ox + args.radius) + 1)
            y0 = max(0, int(oy - args.radius)); y1 = min(WORK, int(oy + args.radius) + 1)
            win = mask[y0:y1, x0:x1]
            ys, xs = np.nonzero(win)
            if len(xs) == 0:
                continue
            gx = xs + x0
            gy = ys + y0
            d = np.sqrt((gx - ox) ** 2 + (gy - oy) ** 2)
            valid = np.array([(int(a), int(b)) not in used for a, b in zip(gx, gy)])
            if not valid.any():
                continue
            d = np.where(valid, d, np.inf)
            i = int(np.argmin(d))
            if d[i] < best_d:
                best_d = float(d[i])
                best = (int(gx[i]), int(gy[i]))

        if best is None or best_d > args.max_move:
            kept += 1
            used.add((int(round(ox)), int(round(oy))))
            details.append((name, "保留", (round(ox * SCALE), round(oy * SCALE)), None, None))
            continue

        nx, ny = best
        used.add(best)
        old = (round(ox * SCALE), round(oy * SCALE))
        new = (nx * SCALE, ny * SCALE)
        st["x"], st["y"] = new
        moved += 1
        details.append((name, "吸附", old, new, round(best_d * SCALE)))

    print(f"\n=== 结果 ===")
    print(f"  吸附: {moved}   保留: {kept}")

    big_moves = [d for d in details if d[4] and d[4] > 150]
    print(f"  大位移(>150px)条数: {len(big_moves)}")
    for name, act, old, new, dist in big_moves[:15]:
        print(f"    {name:<12} {old} → {new}  位移{dist}px")

    if args.dry_run:
        print("\n[DRY-RUN] 未写文件")
        return

    with open(STATIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 已写入 {STATIONS_PATH}")


if __name__ == "__main__":
    main()
