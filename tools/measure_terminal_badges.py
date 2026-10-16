# -*- coding: utf-8 -*-
"""只读：量原图里每条线末端的"线路号方块"，产出 data/terminal_badges.json。

★ 为什么不能靠"沿末段往外推"：试过了，莲塘/溪涌/红岭南/东角头/田心 这 5 个
  原图是**竖着**摆的，按末段方向推出来全是横的，误差 250px 上下。
  原图摆位是"看哪儿有空地就往哪儿放"，推不出来 ⇒ 只能量。

怎么找方块（两道坎 + 一个铁证）：
  ① 种子点要 DT≥8（大方块内部才有这么大的 DT）；
  ② 从种子点只在 DT≥7 的像素里连通 —— 把连在方块上那条 12px 的线切掉
     （线的 DT≤6），拿到的是**方块本身**的 bbox，白字是内部空洞不影响 bbox；
  ③ 铁证：方块正中必须有一片**白像素**（白色数字）——
     换乘胶囊/站点圆点内部没有白，一下就排除了。

用法: python tools/measure_terminal_badges.py
产物: data/terminal_badges.json  {"<线号>|<站名>": {"dx":..,"dy":..,"size":..}}
      （dx/dy = 方块中心相对**这条线自己的站体坐标**的偏移）
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from core.data_manager import get_data_manager          # noqa: E402
from ui.map_view import line_station_xy                 # noqa: E402

RAD = int(os.environ.get("BADGE_RAD", 260))   # 搜索半径
# ★ 种子阈值别再往下调了：调到 8 会把"换乘胶囊"也捞进来（胶囊内部也有白字），
#   还会让方块跟旁边的粗线连成一片、bbox 撑爆过滤区间（太安就是这么丢的）。
DT_SEED = float(os.environ.get("BADGE_DT", 15.0))
BODY_DT = 7.0        # "厚像素"阈值：12px 的线 DT≤6 ⇒ 被排除
EDGE_PAD = 14.0      # bbox 到方块真实边缘 ≈ 2×BODY_DT
# ★ 默认**关掉**（1.1 = 永不拒绝）：太安的"7"是白字带黑描边，中心取到描边上就
#   判成"纯色"被误杀。实测只靠 尺寸(95~150) + 长宽比(≥0.75) + DT(≥15) 三重过滤
#   已经够干净：胶囊 26~50 宽、圆点 ≈48，都进不了 95 这个下限。
SOLID_MAX = float(os.environ.get("BADGE_SOLID", 1.1))
SIZE_LO, SIZE_HI = 95.0, 150.0


def hex2rgb(h):
    h = str(h).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def candidates(sub, rgb):
    """在裁剪图 sub 里找"带白字的实心方块"，返回 [(cy, cx, w, h, dt)]。"""
    r, g, b = rgb
    m = (np.abs(sub[:, :, 0] - r) + np.abs(sub[:, :, 1] - g)
         + np.abs(sub[:, :, 2] - b)) <= 30
    if m.sum() < 500:
        return []
    dt = ndimage.distance_transform_edt(m)
    mx = ndimage.maximum_filter(dt, size=41)
    peaks = (dt >= DT_SEED) & (dt == mx)
    if not peaks.any():
        return []
    body, _nb = ndimage.label(dt >= BODY_DT)
    seen = {}
    for cy, cx in zip(*np.where(peaks)):
        lb = body[cy, cx]
        if lb == 0:
            continue
        d = float(dt[cy, cx])
        if lb not in seen or d > seen[lb][0]:
            seen[lb] = (d, cy, cx)
    out = []
    for lb, (d, cy, cx) in seen.items():
        ys, xs = np.where(body == lb)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        w = (x1 - x0 + 1) + EDGE_PAD
        h = (y1 - y0 + 1) + EDGE_PAD
        if not (SIZE_LO <= max(w, h) <= SIZE_HI):
            continue
        if min(w, h) / float(max(w, h)) < 0.75:
            continue
        # ★ 铁证：方块正中**不能是一整块纯线路色**（里面有个数字）。
        #   站点圆点/换乘胶囊的内部是纯色（占比≈1.0），一票否决。
        #   ★ 别写成"必须有一片白" —— 太安的"7"是**白字带黑描边**，
        #     中心取到描边上就没白了（第一版就是这么把太安误杀的）。
        hw = int(max(w, h) * 0.28)
        inner = sub[max(0, cy - hw):cy + hw, max(0, cx - hw):cx + hw]
        if inner.size == 0:
            continue
        solid = float((np.abs(inner[:, :, 0] - r) + np.abs(inner[:, :, 1] - g)
                       + np.abs(inner[:, :, 2] - b) <= 30).mean())
        if solid > SOLID_MAX:
            continue
        out.append(((y0 + y1) / 2.0, (x0 + x1) / 2.0, w, h, d))
    return out


def main():
    dm = get_data_manager()
    stations = dm.all_stations()
    lines = dm.all_lines()
    img = np.asarray(Image.open(SRC / "assets/shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]

    result = {}
    log = []
    for line in lines:
        lid = str(line.get("id"))
        seq = [s for s in (line.get("stations") or []) if s in stations]
        if len(seq) < 2:
            continue
        rgb = hex2rgb(line.get("color", "#888888"))
        for end_i in (0, -1):
            nm = seq[end_i]
            x, y = line_station_xy(stations[nm], lid)
            x0, y0 = max(0, int(x) - RAD), max(0, int(y) - RAD)
            x1, y1 = min(W, int(x) + RAD), min(H, int(y) + RAD)
            sub = img[y0:y1, x0:x1]
            cands = candidates(sub, rgb)
            if not cands:
                log.append("%-4s %-8s ✗ 没量到（走兜底规则）" % (lid, nm))
                continue
            best = min(cands, key=lambda c: ((x0 + c[1] - x) ** 2 + (y0 + c[0] - y) ** 2) ** 0.5)
            cy, cx, w, h, d = best
            px, py = x0 + cx, y0 + cy
            dx, dy = px - x, py - y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 1e-6:
                continue
            result["%s|%s" % (lid, nm)] = {
                "ux": round(float(dx / dist), 4), "uy": round(float(dy / dist), 4),
                "dist": round(float(dist), 1), "size": round(float(max(w, h)), 1),
            }
            log.append("%-4s %-8s 偏移(%+5.0f,%+5.0f) 距离%5.0f 尺寸%.0fx%.0f DT%.0f"
                       % (lid, nm, dx, dy, (dx * dx + dy * dy) ** 0.5, w, h, d))

    out_path = SRC / "data" / "terminal_badges.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("写出 %s  共 %d 条" % (out_path.name, len(result)))
    print("\n".join(log))


if __name__ == "__main__":
    main()
