"""
tools/restore_official_seed.py
==============================
v2.6.18：把站点坐标**恢复成官方图纸坐标**（8000×8000 位图坐标系），
作为 relayout_octilinear.py 的种子。

为什么不用 v2.6.17 的布局当种子：
  v2.6.17 是在**错误拓扑**上收敛的（13号线穿过西丽、5号线穿过宝安……），
  错误拓扑把局部几何拧变了形（茶光/珠光被翻到 5号线北侧等）。
  拓扑修正后，旧布局的"锚"反而把站点拽回错误一侧 —— 实测绕行比
  反复在 2.5~6.7 之间打地鼠。正解：种子直接回到**官方图纸坐标**
  （数据文件头注明 x/y = 原图像素坐标），让重排在正确的盆地里收敛。

绝大多数站的旧坐标是准的（逐色校验 + 距离变换双重验证），
只有这 10 个站有实锤偏差，用裁图量到的**真药丸位置**覆盖
（每个都注明出处裁图，logs/_audit_*.png / _overlay_*.png）：

  西丽        (2060,4008)  5/7 换乘药丸        ← crop G
  宝安        ( 637,4231)  11号线点            ← crop Q（旧值偏 ~300px）
  机场东      ( 887,3025)  1/12 换乘药丸       ← overlay（旧值偏 ~108px）
  南山        (1314,5789)  11/12 换乘药丸      ← crop U（旧值偏 ~430px）
  大剧院      (4595,5030)  1/2/5 换乘高药丸    ← crop Y（旧值偏 ~330px）
  湖贝        (4884,5030)  2/5 两点中点        ← crop Y（旧值偏 ~290px）
  东门        (4706,4997)  5号线点（新站）     ← crop Y
  西丽高铁站  (1766,4577)  13号线点（新站）    ← crop A
  光明城      (2568,2161)  13/6支 药丸         ← crop T（旧值偏 ~40px）
  坪山围      (6790,3023)  14/16 换乘药丸      ← crop X（旧值偏 ~75px）

用法：
    python tools/restore_official_seed.py          # 演练
    python tools/restore_official_seed.py --apply  # 备份后落盘
"""

import json
import shutil
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS = SRC_ROOT / "data" / "stations.json"
OLD = SRC_ROOT / "data" / "stations.json.bak_relayout_20260929_045045"

FIXED_POS = {
    "西丽": (2060, 4008), "宝安": (637, 4231), "机场东": (887, 3025),
    "南山": (1314, 5789), "大剧院": (4595, 5030), "湖贝": (4884, 5030),
    "东门": (4706, 4997), "西丽高铁站": (1766, 4577),
    "光明城": (2568, 2161), "坪山围": (6790, 3023),
}

# 旧备份里的曾用名（v2.6.17 把"幛背"错字改成了"嶂背"）
RENAMED = {"嶂背": "幛背"}


def main():
    apply = "--apply" in sys.argv
    with open(STATIONS, "r", encoding="utf-8") as f:
        sdoc = json.load(f)
    with open(OLD, "r", encoding="utf-8") as f:
        old = json.load(f)["stations"]
    st = sdoc["stations"]

    n_old = n_fix = n_new = 0
    for name, s in st.items():
        if name in FIXED_POS:
            s["x"], s["y"] = FIXED_POS[name]
            n_fix += 1
        elif name in old:
            s["x"], s["y"] = float(old[name]["x"]), float(old[name]["y"])
            n_old += 1
        elif RENAMED.get(name) in old:
            o = old[RENAMED[name]]
            s["x"], s["y"] = float(o["x"]), float(o["y"])
            n_old += 1
        else:
            print(f"  [WARN] {name} 既无旧坐标也无定案坐标，保持现状 ({s['x']},{s['y']})")
            n_new += 1
    print(f"恢复官方坐标 {n_old} 站 + 定案修正 {n_fix} 站" + (f" + 跳过 {n_new} 站" if n_new else ""))
    assert n_fix == len(FIXED_POS), "定案修正数量对不上"
    assert n_new == 0, "有站没着落"

    if not apply:
        print("（演练模式，未写文件；加 --apply 落盘）")
        return 0
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = STATIONS.with_suffix(STATIONS.suffix + f".bak_official_{ts}")
    shutil.copy2(STATIONS, bak)
    with open(STATIONS, "w", encoding="utf-8") as f:
        json.dump(sdoc, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已落盘（备份 → {bak.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
