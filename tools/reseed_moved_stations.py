"""
tools/reseed_moved_stations.py
==============================
v2.6.18 配套：把「归属被改过 / 原坐标量错了」的站重新播种到合理位置，
然后再跑 relayout_octilinear.py —— 否则锚（λ=0.35）会把这些站拽回
**按旧归属量的旧位置**，在新线上形成大绕行（实测：7号线在西丽绕行 7.26、
12号线在南山绕行 2.49）。

播种规则（不写死坐标）：对该站所属的**每一条线**，取它在线上前一站与
后一站的中点（是端点的那条线跳过），把所有线的中点取平均作为新坐标。
之后由重排统一精调。

清单（都有实锤）：
  西丽        旧坐标量错（真药丸在 ~180px 外），且新加入 7号线
  南山        旧坐标量错 ~400px（11/12 换乘）
  宝安        旧坐标量错 ~300px（11号线）
  机场东      旧坐标量错 ~108px（1/12 换乘）
  湖贝        旧坐标量错 ~280px，且新加入 5号线
  大剧院      旧坐标量错 ~470px，且新加入 5号线
  深大        新加入 13号线（坐标本身没大错，顺手正到两条线走廊中间）
  自然博物馆西 旧坐标正好压在 16号线线上（其实是云巴站）
  坪山围      偏 ~39px    光明城 偏 ~40px    东角头 偏 ~20px

用法：
    python tools/reseed_moved_stations.py 1          # 演练第一轮
    python tools/reseed_moved_stations.py 1 --apply  # 备份后落盘
    python tools/reseed_moved_stations.py 2 --apply  # 第二轮
"""

import json
import shutil
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS = SRC_ROOT / "data" / "stations.json"
LINES = SRC_ROOT / "data" / "lines.json"

ROUNDS = {
    # 第一轮：归属被改/坐标量错的站（在拓扑修复后、第一次重排前跑）
    1: ["西丽", "南山", "宝安", "机场东", "湖贝", "大剧院", "深大",
        "自然博物馆西", "坪山围", "光明城", "东角头"],
    # 第二轮：第一次重排后被求解器翻到线的另一侧的站（实测 7号线在西丽绕行 3.67、
    # 5号线在宝华绕行 2.73）。只动这几个；第一轮的站已被重排精调过，不能再回种子。
    2: ["西丽", "宝华"],
}

# 第二轮（v2.6.18 重排后实测发现）：有些站被求解器翻到了线的另一侧 ——
# 锚只记得 v2.6.17 的旧格局，会把它们拽回错误的一侧。
# ★ 判据：7号线在西丽的绕行 3.67（茶光/珠光被翻到 5号线走廊北侧，
#   官方应在南侧）；5号线在宝华绕行 2.73（宝华被甩到东侧，官方在走廊上）。
# MID_ONLY：播种时只用指定线路的邻站中点（其他线的邻站自己就是翻的，不能用）
MID_ONLY = {"西丽": ["5"], "宝华": ["5"]}
# REFLECT_Y：以某站的 y 为镜面做上下翻转（把翻到北侧的翻回南侧）
REFLECT_Y = {"茶光": "西丽", "珠光": "西丽"}


def main():
    apply = "--apply" in sys.argv
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    if not nums:
        print("用法: reseed_moved_stations.py <轮次> [--apply]   可选轮次:", sorted(ROUNDS))
        return 1
    todo = []
    for n in nums:
        todo += ROUNDS[int(n)]
    with open(STATIONS, "r", encoding="utf-8") as f:
        sdoc = json.load(f)
    with open(LINES, "r", encoding="utf-8") as f:
        doc = json.load(f)
    st = sdoc["stations"]
    seqs = {L["id"]: L["stations"] for L in doc["lines"]}

    for name in todo:
        s = st.get(name)
        assert s, f"{name} 不在 stations.json"
        mids = []
        use = MID_ONLY.get(name) or (s.get("lines") or [])
        for lid in use:
            seq = seqs[lid]
            i = seq.index(name)
            if 0 < i < len(seq) - 1:
                a, b = st[seq[i - 1]], st[seq[i + 1]]
                mids.append(((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2, lid))
        assert mids, f"{name} 每条线都是端点，没法播种"
        nx = sum(m[0] for m in mids) / len(mids)
        ny = sum(m[1] for m in mids) / len(mids)
        dx, dy = nx - s["x"], ny - s["y"]
        print(f"  {name:8s} 移动 ({dx:+.0f},{dy:+.0f})  来源: "
              + ", ".join(f"{m[2]}号线中点" for m in mids))
        s["x"], s["y"] = round(nx, 2), round(ny, 2)

    if 2 in [int(n) for n in nums]:
        for name, mirror in REFLECT_Y.items():
            s, m = st[name], st[mirror]
            ny = 2 * m["y"] - s["y"]
            print(f"  {name:8s} 以 {mirror} 为镜面翻转 y: {s['y']:.0f} → {ny:.0f}")
            s["y"] = round(ny, 2)

    if not apply:
        print("（演练模式，未写文件；加 --apply 落盘）")
        return 0
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = STATIONS.with_suffix(STATIONS.suffix + f".bak_reseed_{ts}")
    shutil.copy2(STATIONS, bak)
    with open(STATIONS, "w", encoding="utf-8") as f:
        json.dump(sdoc, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已落盘（备份 → {bak.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
