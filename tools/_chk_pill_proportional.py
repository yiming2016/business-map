# -*- coding: utf-8 -*-
"""回归：换乘药丸的长度必须**由该站的走廊跨度决定** —— 两端刚好盖住最外侧的两条
线路、再多露一点点。

用户原话（v2.6.25）：「胶囊的左右刚好遮住线路图左和右一点，你现在完全是乱搞比例」。

病灶（v2.6.24 的"等比放大"）：长宽比虽然修好了，但放大倍数来自一个**固定像素下限**
      `SCREEN_TRANSFER_RY`，跟走廊无关 ⇒ 缩放 0.1 时车公庙半长 34.4px，而最外侧
      两条走廊的外缘只有 6.1px —— 药丸比走廊宽 5 倍，左右各甩出去一大截。
正解：半长 = 走廊跨度/2 + 线宽/2 + PILL_OVER（原图就是这么画的：
      车公庙长 128 = 走廊跨 100 + 线宽 22 + 两端各 3）。

★ 判据盯的是**"药丸与走廊的几何关系"**（超出量），不是"长宽比"：
  长宽比只是手段，"刚好遮住线路左右一点"才是目的 —— 盯错不变量就会把
  "贴合走廊但短轴偏窄"的药丸判死（v2.6.24 那版判据就是这么把用户要的改动判死的）。
"""
import os
import sys
import json
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication          # noqa: E402

from ui.metro_render import (StationDotItem, SCREEN_TRANSFER_RX, SCREEN_NORMAL_R,
                             LINE_W_SCENE, PILL_OVER, PILL_MIN_RATIO)   # noqa: E402

OK = []
BAD = []


def check(desc, cond, detail=""):
    (OK if cond else BAD).append(desc)
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", desc,
                           ("   （%s）" % detail) if detail else ""))


_ST = json.load(open(SRC / "data" / "stations.json", encoding="utf-8"))["stations"]
# 这几个站 lanes 里量到了 ≥2 条并排走廊（跨度 52~100 场景单位）
MULTI = ["车公庙", "前海湾", "布吉", "老街", "深圳北站"]


def mk(name, s, old=False):
    """造真图元。old=True ⇒ 开 A/B 开关退回 v2.6.24「固定像素下限」的旧写法。"""
    if old:
        os.environ["METROEDITOR_NO_PILL_PROP"] = "1"
    else:
        os.environ.pop("METROEDITOR_NO_PILL_PROP", None)
    it = StationDotItem(name, dict(_ST[name]))
    it.apply_view_scale(s)
    return it


def over(name, s, old=False):
    """药丸半长 − 最外侧走廊外缘（屏幕px）。= "左右各露出来多少"。"""
    it = mk(name, s, old)
    hw, hl = it.pill_half()
    outer = (it.lane_span_along() * 0.5 + LINE_W_SCENE * 0.5) * s
    return hl - outer


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841

    print("\n===== A：多线站的药丸必须「刚好盖住最外侧走廊 + 一点点」 =====")
    for s in (0.10, 0.16, 0.25, 0.54, 1.00):
        worst, wn = -1e9, ""
        for n in MULTI:
            o = over(n, s)
            hw = mk(n, s).pill_half()[0]
            # 上界：要么就是 PILL_OVER 那一点，要么被"胶囊形状"下限顶起来
            cap = max(PILL_OVER * s, hw * PILL_MIN_RATIO) + 0.8
            if not (0.0 <= o <= cap):
                check("缩放 %.2f %s：超出量在 [0, %.2f] 内" % (s, n, cap), False,
                      "%.2f" % o)
            if o - cap > worst:
                worst, wn = o - cap, n
        check("缩放 %.2f：全部 %d 个多线站都贴合走廊（最差 %s）" % (s, len(MULTI), wn),
              worst < 0, "最差余量 %.2f" % worst)

    print("\n===== B：1:1 档必须跟原图量出来的尺寸一致 =====")
    for n in MULTI:
        it = mk(n, 0.54)
        hw, hl = it.pill_half()
        want = float((_ST[n].get("pill") or {}).get("len", 0.0)) * 0.5 * 0.54
        if want <= 0:
            continue
        # ★ 容差 3px：布吉这类站原图量出的 pill.len(78) 比它自己的走廊跨度
        #   需要的还短 2.5px —— 两个量尺打架时**以走廊为准**（用户要的就是
        #   "左右刚好遮住线路"），所以这里只要求"不比原图短、也不离谱地长"。
        check("%s @0.54：半长 ≈ 原图量出的 %.2f（-0.5 ~ +3px）" % (n, want),
              want - 0.5 <= hl <= want + 3.0, "%.2f" % hl)

    print("\n===== C：变异自检 —— 换回「固定像素下限」的旧写法，超出量必须爆掉 =====")
    # ★ 只在"下限真会触发"的档位做变异：0.30 时忠实值(19.2)已经大于旧下限(13.4)，
    #   两种写法结果一样 ⇒ 在那里做变异自检是**假判据**（变异根本没生效）。
    for s in (0.10, 0.15):
        for n in ("车公庙", "老街"):
            o_old, o_new = over(n, s, old=True), over(n, s)
            check("缩放 %.2f %s：旧写法超出量 ≥ 新写法 3 倍" % (s, n),
                  o_old >= o_new * 3.0 + 0.5,
                  "旧 %.2f vs 新 %.2f" % (o_old, o_new))
    os.environ.pop("METROEDITOR_NO_PILL_PROP", None)

    # ★★ v2.6.54：药丸那道"屏幕最小半径"保底**默认关掉了**（归到 PHYSICAL_MINS
    #   总开关，跟 v2.6.43 关掉的字号/线宽/圆点三个下限同一类）。
    #   理由：它是**屏幕恒定量** ⇒ 小档把药丸在场景里撑大 ⇒ 站名为了不压上去
    #   被顶远（"宝安中心"实测 0.115 档比 0.4 档远 37 场景单位）——正是用户说的
    #   「调好的位置换倍率就错位」。
    #   ⇒ D 段改成验**开关行为**：默认纯等比、开开关保底才回来。
    print("\n===== D：药丸尺寸（默认纯等比 / 开 PHYSICAL_MINS 才保底） =====")
    it = mk("车公庙", 0.125)
    hw, hl = it.pill_half()
    check("缩到 0.125：**默认纯等比**（半宽 = 场景白心 × 缩放，无屏幕保底）",
          abs(hw - it._pill_wid * 0.5 * 0.125) < 1e-6,
          "半宽 %.2f（等比应为 %.2f）" % (hw, it._pill_wid * 0.5 * 0.125))
    check("缩到 0.125：半长 ≥ 半宽 × %.1f（还是胶囊不是圆）" % PILL_MIN_RATIO,
          hl >= hw * PILL_MIN_RATIO - 1e-6, "%.2f ≥ %.2f" % (hl, hw * PILL_MIN_RATIO))
    import ui.metro_render as MR                                    # noqa: E402
    MR.PHYSICAL_MINS = True          # ★ 变异：把总开关打开，保底必须回来
    try:
        hw2, _ = it.pill_half()
        check("开 PHYSICAL_MINS ⇒ 屏幕保底回来（半宽 ≥ SCREEN_TRANSFER_RX）",
              hw2 >= SCREEN_TRANSFER_RX - 1e-6,
              "%.2f ≥ %.2f" % (hw2, SCREEN_TRANSFER_RX))
        check("开 PHYSICAL_MINS ⇒ 换乘站半宽 ≥ 普通站半径（不比普通站小）",
              hw2 >= SCREEN_NORMAL_R - 1e-6, "%.2f ≥ %.2f" % (hw2, SCREEN_NORMAL_R))
    finally:
        MR.PHYSICAL_MINS = False     # 还原，别影响后面

    print("\n" + "=" * 62)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  失败：%s" % b)
    print("=" * 62)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
