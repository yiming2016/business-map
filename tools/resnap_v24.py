"""v2.4 坐标重定位：不再靠"就近白斑吸附"，而是
   OCR 站名  ->  该名字最近的标记  ->  校验该标记确实落在该站某条线的走廊上

依据：
  - ocr_labels.json  原图上真实印出的站名及位置
  - markers.json     原图上检测到的站点标记（圆点/胶囊）
  - audit_offcorridor.LINE_RGB  实测线色 -> 走廊掩膜 -> 每个标记属于哪些线

输出：data/_resnap_report.txt，逐站报告 旧坐标 -> 新坐标 及位移。
用法:
  python tools/resnap_v24.py            # 只出报告
  python tools/resnap_v24.py --apply    # 写回 stations.json（自动备份）
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

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

DS = 2
TOL = 12
SERVE_R = 14.0      # 标记"贴上"某条线走廊的判定距离（原图 px）
NAME_R = 320.0      # OCR 名 -> 标记 的最大距离
MARK_R = 30.0       # 标记中心与 OCR 框中心的合理偏移上限（用于选最近的同名标记）

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

    def dt_at(lid, x, y):
        iy, ix = int(round(y / DS)), int(round(x / DS))
        iy = min(max(iy, 0), dt[lid].shape[0] - 1)
        ix = min(max(ix, 0), dt[lid].shape[1] - 1)
        return float(dt[lid][iy, ix])

    # 每个标记属于哪些线
    served = []
    for m in mk:
        ls = [lid for lid in LINE_RGB if dt_at(lid, m["x"], m["y"]) <= SERVE_R]
        served.append(ls)
    n_none = sum(1 for s in served if not s)
    print(f"标记 {len(mk)} 个，其中 {n_none} 个不贴任何线色走廊")

    # 站名 -> 同名 OCR 框
    byname = {}
    for b in lb:
        t = b["text"].replace(" ", "")
        if not t or not CN.match(t):
            continue
        byname.setdefault(t, []).append((b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, b.get("score", 0)))
    # 别名并入
    for k, v in ALIAS.items():
        if k in byname:
            byname.setdefault(v, []).extend(byname[k])

    lines = []
    report = []
    for n, s in S.items():
        lid_set = set(s.get("lines") or [])
        if not lid_set:
            continue
        # 候选标记：必须同时被该站"所有"线路服务（转乘胶囊）
        strict = [i for i, ls in enumerate(served) if lid_set <= set(ls)]
        if not strict:
            strict = [i for i, ls in enumerate(served) if lid_set & set(ls)]
        if not strict:
            report.append(f"{n:<8s} !! 找不到任何贴线的标记")
            continue
        hits = byname.get(n) or []
        best = None
        for (cx, cy, sc) in hits:
            for i in strict:
                d = math.dist((mk[i]["x"], mk[i]["y"]), (cx, cy))
                if d <= NAME_R and (best is None or d < best[0]):
                    best = (d, i, "OCR名")
        src = "OCR名"
        if best is None:
            # 退化为：靠近当前位置的贴线标记
            for i in strict:
                d = math.dist((mk[i]["x"], mk[i]["y"]), (s["x"], s["y"]))
                if d <= 260 and (best is None or d < best[0]):
                    best = (d, i, "近位")
            src = "近位"
        if best is None:
            report.append(f"{n:<8s} !! 未能定位（线 {sorted(lid_set)}）")
            continue
        d, i, src = best
        nx, ny = round(float(mk[i]["x"]), 1), round(float(mk[i]["y"]), 1)
        shift = math.dist((nx, ny), (s["x"], s["y"]))
        lines.append((n, s["x"], s["y"], nx, ny, shift, src, i))
        report.append(f"{n:<8s} ({s['x']:>7.1f},{s['y']:>7.1f}) -> ({nx:>7.1f},{ny:>7.1f})"
                      f"  位移 {shift:>7.1f}  {src}  线={','.join(sorted(lid_set))}")

    # 冲突：多个站指向同一个标记
    from collections import Counter
    cnt = Counter(x[7] for x in lines)
    clash = {i for i, c in cnt.items() if c > 1}
    if clash:
        report.append("\n===== ★ 多个站抢同一个标记（需人工裁决） =====")
        for i in clash:
            who = [x[0] for x in lines if x[7] == i]
            m = mk[i]
            report.append(f"  标记({m['x']:.0f},{m['y']:.0f}) <- " + "、".join(who))

    big = [x for x in lines if x[5] > 120]
    report.append(f"\n共处理 {len(lines)} 站；位移 >120px 的有 {len(big)} 个；冲突标记 {len(clash)} 个")
    (DATA / "_resnap_report.txt").write_text("\n".join(report), encoding="utf-8")
    print(f"报告已写 -> data/_resnap_report.txt（{len(lines)} 站，大位移 {len(big)}，冲突 {len(clash)}）")
    for r in report:
        print(r)

    if not apply:
        print("\n（未加 --apply，仅报告）")
        return
    ts = datetime.now().strftime("%m%d%H%M")
    shutil.copy2(DATA / "stations.json", DATA / f"stations.json.bak_resnap_{ts}")
    for (n, ox, oy, nx, ny, sh, src, i) in lines:
        S[n]["x"], S[n]["y"] = nx, ny
    (DATA / "stations.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] 已写回（备份 .bak_resnap_{ts}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
