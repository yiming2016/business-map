"""v2.5 坐标重定位（全局一对一最优指派版，修复 v2.4 的"抢标记"缺陷）

v2.4 缺陷：逐站贪心"OCR名 -> 最近标记"没有一对一约束，密集等距站的
OCR 标签中心稍偏就会抢到邻站标记（实测 56 处冲突，如"车公庙"抢"香蜜湖"）。

v2.5 方案：匈牙利算法（scipy.optimize.linear_sum_assignment）全局指派
  - 每个站最多认领一个标记，每个标记最多被一个站认领（冲突数恒为 0）
  - 代价 = min(OCR框中心 -> 标记中心距离)；无 OCR 的站用当前位置距离 + 罚金
  - 换乘站（>=2线）必须拿大标记(max(w,h)>=27)，普通站必须拿小标记，不匹配 +罚金
  - 每站另设一个"保持原坐标"虚拟列（代价 KEEP_PENALTY），全部候选太差时宁可不挪

用法:
  python tools/resnap_v25.py            # 只出报告 -> data/_resnap_report.txt
  python tools/resnap_v25.py --apply    # 写回 stations.json（自动备份）
"""
import json
import math
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

DS = 2
TOL = 12
SERVE_R = 14.0       # 标记"贴上"某条线走廊的判定距离（原图 px）
NAME_R = 320.0       # OCR 框 -> 标记 的最大可用距离
NEAR_R = 260.0       # 无 OCR 站：当前位置 -> 标记 的最大可用距离
KEEP_PENALTY = 150.0 # "保持原坐标"虚拟列代价：OCR 匹配几乎都 <150，宁可靠 OCR
SIZE_PENALTY = 60.0  # 站类型(普通/换乘)与标记尺寸不匹配的罚金
NEAR_PENALTY = 25.0  # 无 OCR 站用"近位"通道的罚金（让有 OCR 的站优先拿标记）
BIG = 1e6

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_offcorridor import LINE_RGB  # noqa: E402

ALIAS = {
    "展中心": "会展中心", "子林": "竹子林", "梅北": "香梅北", "水径": "上水径",
    "留仙": "留仙洞", "见澜": "观澜", "海林关": "梅林关", "公明广": "公明广场",
    "田口岸": "福田口岸", "福田口": "福田口岸", "坪山广": "坪山广场",
    "红公园": "红坳公园", "光明坊": "光明城", "李松荫": "李松蓢", "山广场": "坪山广场",
    "艺城公园": "龙城公园", "宝龙同乐": "宝龙", "区": "会展城", "念馆": "东纵纪念馆",
    "梅林": "梅村", "坪地云": "坪地六联", "深大丽": "深大丽湖",
    "南城": "华南城", "天花": "禾花", "笋岗洪湖": "笋岗",
}
CN = re.compile(r"^[\u4e00-\u9fff]+$")


def main():
    apply = "--apply" in sys.argv
    im = Image.open(IMG).convert("RGB")
    img = np.asarray(im.resize((im.width // DS, im.height // DS), Image.NEAREST))

    dt = {}
    for lid, rgb in LINE_RGB.items():
        c = np.array(rgb, np.int16)
        d = np.zeros(img.shape[:2], np.int16)
        for k in range(3):
            d = np.maximum(d, np.abs(img[:, :, k].astype(np.int16) - c[k]))
        dt[lid] = ndimage.distance_transform_edt(~(d <= TOL)) * DS

    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))
    S = st["stations"]
    mk = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    lb = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))
    M = len(mk)

    def dt_at(lid, x, y):
        iy, ix = int(round(y / DS)), int(round(x / DS))
        iy = min(max(iy, 0), dt[lid].shape[0] - 1)
        ix = min(max(ix, 0), dt[lid].shape[1] - 1)
        return float(dt[lid][iy, ix])

    # 每个标记属于哪些线：在其边界框外扩 PAD 的矩形区域内找线色走廊
    # （圆形 SERVE_R 判定对 27~89px 的大换乘胶囊失效——胶囊中心不贴线）
    PAD = 4.0
    served = []
    for m in mk:
        hw, hh = m["w"] / 2 + PAD, m["h"] / 2 + PAD
        y0 = max(int((m["y"] - hh) / DS), 0)
        y1 = min(int((m["y"] + hh) / DS) + 1, dt["1"].shape[0])
        x0 = max(int((m["x"] - hw) / DS), 0)
        x1 = min(int((m["x"] + hw) / DS) + 1, dt["1"].shape[1])
        ls = []
        for lid in LINE_RGB:
            if y1 <= y0 or x1 <= x0:
                continue
            if float(dt[lid][y0:y1, x0:x1].min()) <= SERVE_R:
                ls.append(lid)
        served.append(ls)
    msize = [max(m["w"], m["h"]) for m in mk]  # 换乘胶囊 >=27，普通圆点 24~25

    # 站名 -> 同名 OCR 框中心列表
    byname = {}
    for b in lb:
        t = b["text"].replace(" ", "")
        if not t or not CN.match(t):
            continue
        byname.setdefault(t, []).append((b["x"] + b["w"] / 2, b["y"] + b["h"] / 2))
    for k, v in ALIAS.items():
        if k in byname:
            byname.setdefault(v, []).extend(byname[k])

    names = list(S.keys())
    N = len(names)

    # ---------- 换乘站（>=2 线）：不走标记指派，直接在原图上找
    # "多线走廊交汇点"（min-max：让离自己每条线走廊都尽量近的点）。
    # 原因：4 线枢纽的巨型胶囊常未被 markers.json 检出（strict=0），
    # 指派拿不到标记；而走廊交汇不依赖标记检测。
    XF_WIN = 260.0      # 搜索窗口半径（OCR框/当前位置 为中心）
    XF_STEP = 2.0       # 搜索步长（原图 px）
    # 灰色系走廊（有轨电车/云巴）满图蔓延、不唯一，绝不能参与 min-max 交汇，
    # 否则 f=max(...) 退化为"窗口内任意灰线点"，导致满图乱飞（清湖飞 1385px 实测）
    GRAY = {"有轨电车", "有轨电车支线", "坪山云巴"}
    # 视觉核对发现的问题站：12/20 平行走廊区 min-max 选错交汇点（挪到会展城），
    # v2.4 标记检测值 (521,2082.5) 可靠，强制保持
    # 莲塘：2/8 换乘胶囊在 (5920,5125)，min-max 北移 124px 到折线段属误判
    SKIP_RESNAP = {"国展北", "莲塘"}
    report = []
    lines_out = []
    kept, failed = [], []
    xfer_done = set()
    for n in names:
        s = S[n]
        lid_set = set(s.get("lines") or [])
        if len(lid_set) < 2:
            continue
        lids_use = lid_set - GRAY
        if n in SKIP_RESNAP or not lids_use:
            kept.append(n)
            report.append(f"{n:<8s} ( {s['x']:>7.1f},{s['y']:>7.1f}) -> 保持原坐标（纯灰色系换乘）")
            xfer_done.add(n)
            continue
        hits = byname.get(n) or []
        if hits:
            # OCR 框可能在图上别处撞名（如"清湖"飞 1385px 实测）：
            # 只取离当前位置最近的框，且距离 >500 视为不可信，退回当前位置
            cx, cy = min(hits, key=lambda h: math.dist(h, (s["x"], s["y"])))
            if math.dist((cx, cy), (s["x"], s["y"])) > 500:
                cx, cy = s["x"], s["y"]
                src = "近位"
            else:
                src = "OCR名"
        else:
            cx, cy = s["x"], s["y"]
            src = "近位"
        best = None
        yy = cy - XF_WIN
        while yy <= cy + XF_WIN:
            xx = cx - XF_WIN
            iy = min(max(int(round(yy / DS)), 0), dt["1"].shape[0] - 1)
            while xx <= cx + XF_WIN:
                ix = min(max(int(round(xx / DS)), 0), dt["1"].shape[1] - 1)
                f = max(dt[lid][iy, ix] for lid in lids_use)
                # 轻微偏向窗口中心，避免平局时飘到窗口边
                f += math.dist((xx, yy), (cx, cy)) * 0.01
                if best is None or f < best[0]:
                    best = (f, xx, yy)
                xx += XF_STEP
            yy += XF_STEP
        if best is None:
            kept.append(n)
            report.append(f"{n:<8s} ( {s['x']:>7.1f},{s['y']:>7.1f}) -> 保持原坐标（换乘定位失败）")
            continue
        _, nx, ny = best
        nx, ny = round(nx, 1), round(ny, 1)
        shift = math.dist((nx, ny), (s["x"], s["y"]))
        lines_out.append((n, s["x"], s["y"], nx, ny, shift, "换乘交汇", -1))
        report.append(f"{n:<8s} ({s['x']:>7.1f},{s['y']:>7.1f}) -> ({nx:>7.1f},{ny:>7.1f})"
                      f"  位移 {shift:>7.1f}  换乘交汇({src})  线={','.join(sorted(lid_set))}")
        xfer_done.add(n)

    # ---------- 普通站（1 线）：全局一对一标记指派 ----------
    xfer_names = set(xfer_done)
    plain = [n for n in names if n not in xfer_names and (S[n].get("lines") or [])]
    M = len(mk)
    P = len(plain)
    ncol = M + P
    cost = np.full((P, ncol), BIG, dtype=np.float64)
    for r, n in enumerate(plain):
        s = S[n]
        lid_set = set(s["lines"])
        cands = [i for i, ls in enumerate(served) if lid_set <= set(ls)]
        if not cands:
            cands = [i for i, ls in enumerate(served) if lid_set & set(ls)]
        if not cands:
            continue
        hits = byname.get(n) or []
        for i in cands:
            mx, my = mk[i]["x"], mk[i]["y"]
            if hits:
                d = min(math.dist((mx, my), (cx, cy)) for cx, cy in hits)
                if d > NAME_R:
                    continue
            else:
                d = math.dist((mx, my), (s["x"], s["y"])) + NEAR_PENALTY
                if d > NEAR_R:
                    continue
            if msize[i] >= 27:  # 普通站不拿换乘大胶囊
                d += SIZE_PENALTY
            cost[r, i] = d
        cost[r, M + r] = KEEP_PENALTY

    row, col = linear_sum_assignment(cost)
    for r, c in zip(row, col):
        n = plain[r]
        s = S[n]
        if c >= M:
            kept.append(n)
            report.append(f"{n:<8s} ( {s['x']:>7.1f},{s['y']:>7.1f}) -> 保持原坐标（无可靠标记）")
            continue
        d = cost[r, c]
        nx, ny = round(float(mk[c]["x"]), 1), round(float(mk[c]["y"]), 1)
        shift = math.dist((nx, ny), (s["x"], s["y"]))
        src = "OCR名" if d < NEAR_PENALTY + NAME_R else "近位"
        lines_out.append((n, s["x"], s["y"], nx, ny, shift, src, c))
        report.append(f"{n:<8s} ({s['x']:>7.1f},{s['y']:>7.1f}) -> ({nx:>7.1f},{ny:>7.1f})"
                      f"  位移 {shift:>7.1f}  {src}  代价{d:.0f}")

    # 冲突复核（应为 0；换乘站 c=-1 不参与标记冲突统计）
    from collections import Counter
    cnt = Counter(x[7] for x in lines_out if x[7] >= 0)
    clash = {i for i, c0 in cnt.items() if c0 > 1}
    big = [x for x in lines_out if x[5] > 120]
    report.append("")
    report.append(f"共处理 {N} 站：移动 {len(lines_out)}，保持原位 {len(kept)}，"
                  f"跳过 {len(failed)}；冲突标记 {len(clash)}；位移>120px {len(big)}")
    if kept:
        report.append("保持原位（需人工复核）：" + "、".join(kept))
    if clash:
        report.append("★ 仍有冲突（异常）：")
        for i in clash:
            who = [x[0] for x in lines_out if x[7] == i]
            report.append(f"  标记({mk[i]['x']:.0f},{mk[i]['y']:.0f}) <- " + "、".join(who))

    (DATA / "_resnap_report.txt").write_text("\n".join(report), encoding="utf-8")
    print(f"移动 {len(lines_out)} / 保持 {len(kept)} / 跳过 {len(failed)}；"
          f"冲突 {len(clash)}；大位移 {len(big)}")
    for r0 in report:
        if r0.startswith(("共", "保持原位", "★")) or "!!" in r0:
            print(r0)

    if not apply:
        print("\n（未加 --apply，仅报告）")
        return
    ts = datetime.now().strftime("%m%d%H%M")
    shutil.copy2(DATA / "stations.json", DATA / f"stations.json.bak_resnap_{ts}")
    for (n, ox, oy, nx, ny, sh, src, i) in lines_out:
        S[n]["x"], S[n]["y"] = nx, ny
    (DATA / "stations.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] 已写回（备份 .bak_resnap_{ts}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
