"""
tools/restore_v2617_with_official_inserts.py
============================================
v2.6.18 定稿：布局 = **v2.6.17 的成熟布局**为底，只对「新线上没有着落」的
**5 个站**在 v2.6.17 坐标系内做邻站中点播种，然后跑 relayout_octilinear.py。

前五轮实测的教训（都写在各工具注释里）：
  · 给「拓扑没变」的站（南山/宝安/机场东/光明城/湖贝/大剧院）重新播种
    ⇒ 播种坐标和 v2.6.17 自洽位置冲突，求解器把整段翻到线的另一侧
    （茶光/珠光翻到 5号线北侧、宝华甩到东侧、兴围绕行 6.68）。
    ★ 拓扑没变的站，v2.6.17 的位置本来就是自洽的 —— **一个都不要动**。
  · 官方种子整体重排 ⇒ 好区域也被重新掷骰子（南油西绕行 7.42）。
  · 官方坐标+位差嵌入 ⇒ 邻站自己量错了会互相污染（东门/大剧院挤一起）。
  ★ 正解：只有「线上新来」的站需要播种，且种子用 **v2.6.17 坐标系内**
    的邻站中点（同一条走廊，求解器只是把它掰直一点，不会翻车）。

6 个播种站，两种播法：
  【局部坐标架嵌入】（官方图在该站是**笔直**的，用官方几何关系播种）
    西丽   官方架(留仙洞→大学城) + 官方架(西丽湖→茶光)，两线结果取平均
    深大   官方架(桃园→高新园) + 官方架(粤海门→高新中)
    宝华   官方架(临海→宝安中心)    ★ 拓扑没变，但它的 v2.6.17 位置是被
           已删除的「宝安」带歪的（官方绕行 1.14 ≈ 直，当前底图绕行 2.7）
  【邻站中点】（新站/官方邻站本身量歪的，用 v2.6.17 坐标系内中点）
    东门        mid(湖贝, 大剧院)      新站（5号线西延；湖贝/大剧院官方坐标量歪过）
    西丽高铁站  mid(高新北, 石鼓)      新站（13号线）
    坪山围      avg( mid(锦龙,坪山广场), mid(坪环,六和) )   新加入 14号线

★ 教训 1：换乘站播种只用一条线 ⇒ 站被留在那条线的走廊上，另一条线被迫
  大拐弯（实测：西丽只用 7号线 ⇒ 5号线绕行 2.40；深大只用 13号线 ⇒ 1号线
  绕行 3.55，裁图亲眼看到绿线翻山）。
★ 教训 2：两条线中点再平均也不行 —— v2.6.17 里两条走廊**根本不相交**
  （延长线交点在线段外 t=1.37/u=3.78），平均点落在两条走廊中间的无人区，
  求解器直接把站甩飞（7号线西丽绕行 7.49）。
★ 正解「局部坐标架嵌入」：在官方坐标系（bak_relayout_20260930_021126 =
  位图像素坐标）里算该站相对邻站段的 (沿线比例 t, 垂直偏移 s)，再套到
  v2.6.17 的同名邻站上 —— 官方是直的，嵌过来就是直的，且不依赖两条走廊
  在 v2.6.17 里是否相交。实测官方坐标系下这些站的绕行比全是 1.00~1.14。

用法：
    python tools/restore_v2617_with_official_inserts.py          # 演练
    python tools/restore_v2617_with_official_inserts.py --apply  # 备份后落盘
"""

import json
import shutil
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS = SRC_ROOT / "data" / "stations.json"
LINES = SRC_ROOT / "data" / "lines.json"
BASE = SRC_ROOT / "data" / "stations.json.bak_topo_20260930_015013"  # v2.6.17 布局
OFFICIAL = SRC_ROOT / "data" / "stations.json.bak_relayout_20260930_021126"  # 官方像素坐标

# 局部坐标架嵌入：{站: [用哪些线的邻站段做坐标架]}（官方几何 → v2.6.17）
FRAME_SEED = {
    "西丽": ["5", "7"],
    "深大": ["1", "13"],
    "宝华": ["5"],
}
# 邻站中点：{站: [用哪些线的邻站中点]} —— 换乘站必须列全它所有的线
SURGICAL = {
    "东门": ["5"],
    "西丽高铁站": ["13"],
    "坪山围": ["14", "16"],
}


def frame_embed(so, sa_o, sb_o, sa_b, sb_b):
    """官方段 (sa_o→sb_o) 里站 so 的 (t,s) → 套到底图段 (sa_b→sb_b) 上。
    t = 沿线比例，s = 垂直偏移 / 段长（带符号，左正右负）。"""
    ox, oy = sb_o[0] - sa_o[0], sb_o[1] - sa_o[1]
    L2 = ox * ox + oy * oy
    assert L2 > 1, "官方坐标架段长为 0"
    t = ((so[0] - sa_o[0]) * ox + (so[1] - sa_o[1]) * oy) / L2
    s = ((so[0] - sa_o[0]) * oy - (so[1] - sa_o[1]) * ox) / L2  # 叉积/|d|²
    bx, by = sb_b[0] - sa_b[0], sb_b[1] - sa_b[1]
    return (sa_b[0] + t * bx + s * by, sa_b[1] + t * by - s * bx)


def main():
    apply = "--apply" in sys.argv
    with open(STATIONS, "r", encoding="utf-8") as f:
        sdoc = json.load(f)
    with open(LINES, "r", encoding="utf-8") as f:
        ldoc = json.load(f)
    with open(BASE, "r", encoding="utf-8") as f:
        base = json.load(f)["stations"]
    with open(OFFICIAL, "r", encoding="utf-8") as f:
        off = json.load(f)["stations"]
    st = sdoc["stations"]
    seqs = {L["id"]: L["stations"] for L in ldoc["lines"]}

    n_base = 0
    for name, s in st.items():
        if name in SURGICAL or name in FRAME_SEED:
            continue
        if name not in base:
            print(f"  [FAIL] {name} 不在 v2.6.17 布局里，也不在播种清单里")
            return 1
        s["x"], s["y"] = float(base[name]["x"]), float(base[name]["y"])
        n_base += 1
    print(f"恢复 v2.6.17 布局 {n_base} 站")

    for name, lids in SURGICAL.items():
        s = st[name]
        pts = []
        for lid in lids:
            seq = seqs[lid]
            i = seq.index(name)
            assert 0 < i < len(seq) - 1, f"{name} 在 {lid}号线是端点，没法取中点"
            a, b = base[seq[i - 1]], base[seq[i + 1]]
            pts.append(((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2, lid))
        nx = sum(p[0] for p in pts) / len(pts)
        ny = sum(p[1] for p in pts) / len(pts)
        s["x"], s["y"] = round(nx, 2), round(ny, 2)
        print(f"  播种 {name:8s} → ({nx:.0f},{ny:.0f})  ["
              + ", ".join(f"{p[2]}号线中点" for p in pts) + "]")

    for name, lids in FRAME_SEED.items():
        s = st[name]
        pts = []
        for lid in lids:
            seq = seqs[lid]
            i = seq.index(name)
            assert 0 < i < len(seq) - 1, f"{name} 在 {lid}号线是端点，没法做坐标架"
            na, nb = seq[i - 1], seq[i + 1]
            p = frame_embed(
                (off[name]["x"], off[name]["y"]),
                (off[na]["x"], off[na]["y"]), (off[nb]["x"], off[nb]["y"]),
                (base[na]["x"], base[na]["y"]), (base[nb]["x"], base[nb]["y"]))
            pts.append((p[0], p[1], lid, na, nb))
        nx = sum(p[0] for p in pts) / len(pts)
        ny = sum(p[1] for p in pts) / len(pts)
        s["x"], s["y"] = round(nx, 2), round(ny, 2)
        print(f"  架嵌 {name:8s} → ({nx:.0f},{ny:.0f})  ["
              + ", ".join(f"{p[2]}号线架({p[3]}→{p[4]})" for p in pts) + "]")

    if not apply:
        print("（演练模式，未写文件；加 --apply 落盘）")
        return 0
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = STATIONS.with_suffix(STATIONS.suffix + f".bak_v2617base_{ts}")
    shutil.copy2(STATIONS, bak)
    with open(STATIONS, "w", encoding="utf-8") as f:
        json.dump(sdoc, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已落盘（备份 → {bak.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
