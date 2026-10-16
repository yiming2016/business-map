# -*- coding: utf-8 -*-
"""构建期：从官方原图里抽出每条线的"走廊中心线点云"，供**自动追踪**用。

背景（用户原话）：「我还是无法让线条跟随下方的底图」。

我们的线路是"站点直连 + 八向折角"画出来的，跟官方原图那条**真的线**对不上。
官方原图 8000×8000，**1 个原图像素 == 1 个场景单位**（见 map_view.UNDERLAY_SCENE），
所以只要把原图里"这条线的颜色"抽成中心线，就能让画出来的线直接照着它走。

做法：
  1. 按 lines.json 的颜色做 mask（容差 TOL，取**通道最大差**，防止 6号线/3号线互串）；
  2. ★★ 只在**本线站点连线附近 ROI 半径**内保留 mask —— 不加这一步，
     9号线(#8A6B70 褐)、12号线(#A891B0 淡紫)、有轨电车(#B6B6B7 灰)会连
     **站名文字和图例**一起吸进来（实测抽到 8~11 万个点，文件 9MB，全是噪声）；
  3. 连通域去渣：丢掉面积 < MIN_AREA 的块（文字块比走廊小一个量级）；
  4. 对 mask 做距离变换 DF，**每 CELL×CELL 小格里取 DF 最大的那个像素** —— 那就是
     走廊的中心线点（不是整条 22px 宽的带子）；
  5. 落盘 `data/trace_cloud.json`：{"<线号>": [[x, y], ...]}（原图像素 == 场景单位）。

★ ROI 用**真正画出来的那条折线**（`build_line_points_ex`），不是站心直连 ——
  换乘站有走廊偏移，直连会偏离真实走廊上百像素，把 ROI 套错地方。
★ 同色的 2/8 号线、三条灰色线，靠 ROI 各自限定在自己站点附近，不会互相串。

产物只含坐标，运行时**不需要 numpy/PIL**（打包体积小、启动快）。

自检：逐站报"到本线中心线的最近距离"。如果 mask 抽错了，这个数会普遍很大。

用法：
    <分析 venv python> tools/build_trace_cloud.py
"""
import json
import sys
import os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import numpy as np                       # noqa: E402
from PIL import Image                    # noqa: E402
from scipy import ndimage                # noqa: E402

Image.MAX_IMAGE_PIXELS = None

TOL = 32            # 颜色容差（通道最大差）。★ 必须 < 41：6号线 #00C4B5 与
                    #   3号线 #00A6DE 的 B 通道差 41，再大就互相串线了。
CELL = 8            # 中心线点云的采样格边长（原图像素）
ROI = 200           # 只保留"本线折线 ±ROI 像素"范围内的颜色像素
MIN_AREA = 3000     # 连通域小于这个面积就当渣（文字/图例）丢掉
MIN_PTS = 40        # 一条线少于这么多点就当抽错了，写进报告


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def roi_mask(shape, pts_xy, radius):
    """把折线 `pts_xy` 加粗成 2*radius 宽的带子，返回 bool 掩膜。"""
    from PIL import ImageDraw
    H, W = shape
    im = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(im)
    if len(pts_xy) >= 2:
        dr.line([tuple(p) for p in pts_xy], fill=255, width=int(radius * 2), joint="curve")
    return np.array(im) > 0


def main():
    from PySide6.QtWidgets import QApplication
    from ui.map_view import build_line_points_ex
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841

    st = json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]
    lj = json.loads((SRC / "data" / "lines.json").read_text(encoding="utf-8"))
    lines = lj["lines"] if isinstance(lj, dict) else lj

    img = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")).astype(np.int16)
    H, W = img.shape[:2]
    print("原图 %dx%d  TOL=%d  CELL=%d  ROI=%d" % (W, H, TOL, CELL, ROI))

    out = {}
    report = []
    for L in lines:
        lid = str(L.get("id"))
        seq = L.get("stations") or []
        c = np.array(hex2rgb(L.get("color", "#000000")), dtype=np.int16)
        d = np.abs(img - c).max(axis=2)
        mask = d <= TOL

        # —— ROI：只留本线折线附近 ——
        pts_q = build_line_points_ex(lid, seq, st)[0]
        pl = [(float(p.x()), float(p.y())) for p in pts_q]
        if len(pl) >= 2:
            mask &= roi_mask((H, W), pl, ROI)
        npx = int(mask.sum())

        # —— 去渣：丢掉小连通域 ——
        if npx > 0:
            lab, nl = ndimage.label(mask)
            if nl > 1:
                sizes = np.bincount(lab.ravel())
                keep = np.zeros(nl + 1, dtype=bool)
                keep[1:] = sizes[1:] >= MIN_AREA
                mask = keep[lab]
                npx = int(mask.sum())
        if npx < 200:
            report.append((lid, L.get("color"), 0, 0.0, "像素太少 %d" % npx))
            out[lid] = []
            continue

        df = ndimage.distance_transform_edt(mask)
        # 每个 CELL×CELL 小格里取 DF 最大的像素 = 走廊中心线
        gh, gw = H // CELL, W // CELL
        sub_df = df[:gh * CELL, :gw * CELL].reshape(gh, CELL, gw, CELL)
        flat = sub_df.transpose(0, 2, 1, 3).reshape(gh, gw, CELL * CELL)
        am = flat.argmax(axis=2)
        mx = flat.max(axis=2)
        ok = mx > 0.0
        gy, gx = np.nonzero(ok)
        k = am[gy, gx]
        ky, kx = (k // CELL), (k % CELL)
        px = gx * CELL + kx + 0.5
        py = gy * CELL + ky + 0.5
        pts = np.stack([px, py], axis=1)
        out[lid] = [[int(round(float(a))), int(round(float(b)))] for a, b in pts]

        # —— 自检：每个站到本线中心线的最近距离 ——
        seq = L.get("stations") or []
        ds = []
        for name in seq:
            s = st.get(name)
            if not s:
                continue
            sx, sy = float(s.get("x", 0)), float(s.get("y", 0))
            dd = ((pts[:, 0] - sx) ** 2 + (pts[:, 1] - sy) ** 2) ** 0.5
            ds.append(float(dd.min()))
        if ds:
            worst = max(ds)
            avg = sum(ds) / len(ds)
            bad = sum(1 for v in ds if v > 60)
            flag = "" if (len(pts) >= MIN_PTS and avg < 40) else "★疑抽错"
            report.append((lid, L.get("color"), len(pts), avg,
                           "最远 %.0f 平均 %.0f >60px 的站 %d %s" % (worst, avg, bad, flag)))
        else:
            report.append((lid, L.get("color"), len(pts), 0.0, "无站"))

    print("\n线号   颜色      点数   站到中心线平均距离")
    for lid, col, n, avg, note in report:
        print("%-6s %-9s %5d  %6.1f   %s" % (lid, col, n, avg, note))

    dst = SRC / "data" / "trace_cloud.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print("\n已写入 %s  (%.0f KB)" % (dst, dst.stat().st_size / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
