# -*- coding: utf-8 -*-
"""修 2 号线「后海 → 科苑」的歪（用户：「2号线的后海站线路有些歪」）。

═══ 病因（用官方原图逐点量出来的，不是猜的）═══

原图量尺（`assets/shenzhen_metro.png`，像素 == 场景单位，2 号线色 #B05000）：

  · 竖段：x 中心 = **1715**，从 y≈6140 一直到 y≈5845 笔直；
  · 拐弯：**圆角 90°**，从 (1715, 5845) 到 (1798, 5762)，圆心 (1798,5845) 半径 **83**
          （逐点核对：φ=80° 处模型 x=1716.3 / 官方 1715.5；φ=90° 处 1715.0/1715.0）；
  · 东段：y 中心 = **5762**，从 x≈1787 一路向东到红树湾。

我的线为什么歪 —— 两处锚位（`stations.json` 的 `lanes["2"]`）量错了：

  ① **后海**：站体 (1740,5924)，lanes["2"] = [-20.3, ...] ⇒ 锚 x = 1719.7，
     而官方竖段中心是 **1715** ⇒ 线在站上被顶出去 **4.7px**、画成一个来回的小折角。
     ⇒ 改正 dx = **-25.0**（1740-25 = 1715）。
  ② **科苑**：站体 (1765,5769)，lanes["2"] = [13.6, 21.0, ...] ⇒ 锚 (1778.6, 5790.0)。
     官方圆弧在 x=1765 处的中心线 y = 5845-83·cos(asin((1798-1765)/83)) = **5768.8**
     ⇒ 锚该是 **(1765, 5769)**（= 站中心），现在是 (1778.6,5790)：
     **x 偏右 13.6、y 偏下 21.0**，于是折线走成
         (1715,5831) → (1735,5786) → (1778.6,5790) → (1797,5762)
     中间那段"往右还往下沉 4px"再"往上抬 28px" —— 就是用户看到的歪。
     ⇒ 改正 lanes["2"] = [**0.0, 0.0**, ...]。
     ★ 第 3/4 位（走廊走向角 147.1 / 拟合长度 2.43）**不动**：
       `d[3] = 2.43 < 3.0` ⇒ map_view 根本不会用它插"走廊替身点"，改它没有意义。

同时把 `lines.json` 的 `traced` 里**写死的这两个锚点**一起改（描线路径的第一/最后一点
就是两站的锚位，`_traced_fresh()` 也拿它们对账）：

  · "2|登良|后海"   末点 (1719.7,5923.8) → **(1715, 5923.8)**
  · "2|后海|科苑"   首点同上、末点 (1778.6,5790) → **(1765, 5768.8)**，
                    中间按官方**圆弧**重采样（原来只有 2 个点，把弧画成了折角）
  · "2|科苑|红树湾" 首点 (1778.6,5790) → **(1765, 5768.8)**，
                    并按圆弧补 2 个点再接原来的 (1797,5762)…

★ 干净利落的一条判据：改完之后 2 号线从 登良 到 红树湾 的折线**每一段的走向单调**
  （不再有"右→下→右"那种回折）。

用法：
    python tools/fix_fit_houhai.py            # 只算不改（打印前后对照）
    python tools/fix_fit_houhai.py --apply    # 落盘
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
S_FILE = DATA / "stations.json"
L_FILE = DATA / "lines.json"

APPLY = "--apply" in sys.argv

# ---- 官方量的圆弧参数（原图像素 == 场景单位）----
ARC_C = (1798.0, 5845.0)      # 圆心
ARC_R = 83.0                  # 半径


def arc_pt(phi_deg):
    """圆弧上的点。φ=0 ⇒ 东向切点 (1798,5762)；φ=90 ⇒ 北向切点 (1715,5845)。"""
    a = math.radians(phi_deg)
    return [round(ARC_C[0] - ARC_R * math.sin(a), 1),
            round(ARC_C[1] - ARC_R * math.cos(a), 1)]


# 科苑锚位 = 圆弧在 x=1765 处的点
PHI_KEY = math.degrees(math.asin((ARC_C[0] - 1765.0) / ARC_R))    # ≈ 23.43°
KEY = arc_pt(PHI_KEY)                                            # ≈ (1765, 5768.8)


def arc_seq(p0, p1, step=15.0):
    """从 φ=p0 到 φ=p1 采样（含两端），保证点数够把弧画圆。"""
    n = max(1, int(round(abs(p1 - p0) / step)))
    return [arc_pt(p0 + (p1 - p0) * k / n) for k in range(n + 1)]


def main():
    doc = json.loads(L_FILE.read_text(encoding="utf-8"))
    st_doc = json.loads(S_FILE.read_text(encoding="utf-8"))
    st = st_doc["stations"]
    tr = doc.get("traced") or {}

    print("圆弧参数：圆心 (%.0f,%.0f) 半径 %.0f" % (ARC_C[0], ARC_C[1], ARC_R))
    print("科苑锚位 = 圆弧 φ=%.2f° 处 = (%.1f, %.1f)" % (PHI_KEY, KEY[0], KEY[1]))

    # ---------- ① 锚位 ----------
    ho = st["后海"]["lanes"]["2"]
    ky = st["科苑"]["lanes"]["2"]
    print("\n后海 lanes['2'] : %s  →  dx -20.3→-25.0（锚 x 1740-25 = 1715 = 官方中心）" % ho)
    print("科苑 lanes['2'] : %s  →  [0.0, 0.0]（锚 = 站中心 (1765,5769)，正在圆弧上）" % ky)
    ho[0] = -25.0
    ky[0] = 0.0
    ky[1] = 0.0

    # ---------- ② traced 端点 + 圆弧重采样 ----------
    A = "2|登良|后海"
    B = "2|后海|科苑"
    C = "2|科苑|红树湾"
    for k in (A, B, C):
        if k not in tr:
            print("★ 缺段 %s —— 中止" % k)
            return 1

    def dedup(P, tol=1.5):
        """去掉相邻的重复点（圆弧采样点常与原有折点几乎重合）。"""
        out = []
        for p in P:
            if out and math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) < tol:
                continue
            out.append(list(p))
        return out

    # ★ 后海锚位 (1715, 5923.8)、科苑锚位 KEY —— 三段的接缝必须**逐字节相等**，
    #   否则 `_traced_fresh()` 的对账会多出零点几像素的噪声。
    HOU = [1715.0, 5923.8]
    new_A = dedup([[1715.0, 6154.0], [1715.0, 5956.0], HOU])
    new_B = dedup([HOU] + arc_seq(90.0, PHI_KEY))
    new_C = dedup(arc_seq(PHI_KEY, 0.0) + [list(p) for p in tr[C][1:]])
    new_B[-1] = list(KEY)
    new_C[0] = list(KEY)

    for nm, seg, old in (("2|登良|后海", new_A, tr[A]),
                         ("2|后海|科苑", new_B, tr[B]),
                         ("2|科苑|红树湾", new_C, tr[C])):
        print("\n%s   %d 点 → %d 点" % (nm, len(old), len(seg)))
        print("   旧: %s" % old)
        print("   新: %s" % seg)

    tr[A], tr[B], tr[C] = new_A, new_B, new_C
    doc["traced"] = tr

    if not APPLY:
        print("\n（未落盘；加 --apply 才写）")
        return 0
    S_FILE.write_text(json.dumps(st_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    L_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已写入：%s\n        %s" % (S_FILE, L_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
