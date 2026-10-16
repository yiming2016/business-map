# -*- coding: utf-8 -*-
"""v2.6.6 —— 判据：线路下拉菜单的文字，颜色必须等于该线路的**官方色**。

为什么不全信肉眼：
    The current model can't view images，所以"看起来是彩色的"没法确认。
    这里把观感变成数出来的数字 —— 对每条线路，数一数画面里有多少像素
    落在"它的官方色 ±TOL"这个色球里，并要求：
      · 数量 >= MIN_PX（真的把这段字画出来了）
      · 这段颜色的**质心 x** 随选线顺序单调递增（各段各占一段横向区间，没串行）
      · 别的线路色的像素数远小于它自己（没串色）

用法：
    python tools/_chk_lines_color_v266.py            # 正常，应当全过
    python tools/_chk_lines_color_v266.py --mutate-plain   # 变异：全刷成默认灰，必须出现失败
"""
import sys
import os
import json
import argparse
from itertools import combinations

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)

# ★ 测试脚本不许写真数据（这里只读 lines.json / stations.json，不落盘，没问题）

from PySide6.QtCore import Qt                      # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

import ui.widgets as W                              # noqa: E402
from ui.widgets import LinesSelect, LinesPopup, LINE_TEXT_FALLBACK  # noqa: E402

TOL = 34          # 每个通道允许的抗锯齿误差
MIN_PX = 20       # 一段 2~3 字的线路名，实心填充像素的保守下界


# ---------------------------------------------------------------- 数据
def load_lines():
    p = os.path.join(SRC, "data", "lines.json")
    d = json.load(open(p, encoding="utf-8"))
    return d["lines"] if isinstance(d, dict) else d


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- 像素
def to_rgb_image(pm):
    """贴到白底上再转 RGB32：避免 alpha 导致 pixelColor 读到预乘后的怪值。"""
    img = QImage(pm.size(), QImage.Format_RGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    p.drawPixmap(0, 0, pm)
    p.end()
    return img


def count_color(img, target):
    """返回 (命中像素数, 质心x, 质心y)。命中 = 三通道都在 target ±TOL 内。"""
    R, G, B = target
    n = 0
    sx = sy = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - R) <= TOL and abs(c.green() - G) <= TOL
                    and abs(c.blue() - B) <= TOL):
                n += 1
                sx += x
                sy += y
    return n, (sx / n if n else -1.0), (sy / n if n else -1.0)


def cdist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def pick_lines(lines, k=4):
    """挑 k 条**互相颜色距离最大**的线路做样本。

    ★ 为什么不能随便挑：两条色太近（比如 4/10 号线）串了色也数不出差别，
      变异自检就会"看不出问题"。样本本身要足够可分辨。
    """
    cands = [ln for ln in lines if str(ln.get("color", "")).startswith("#")]
    best = None
    for combo in combinations(cands, k):
        cols = [hex2rgb(ln["color"]) for ln in combo]
        d = min(cdist(a, b) for a, b in combinations(cols, 2))
        if best is None or d > best[0]:
            best = (d, combo)
    return list(best[1]), best[0]


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate-plain", action="store_true",
                    help="变异：把线路色全刷成默认灰，判据必须失败")
    args = ap.parse_args()

    lines = load_lines()
    if args.mutate_plain:
        # 变异要**真的生效**：LinesPopup 在构造时就把颜色读进样式表了，
        # 所以必须在造控件之前换掉取色函数。
        W.line_text_color = lambda *_a, **_k: LINE_TEXT_FALLBACK

    sample, min_dist = pick_lines(lines, 4)
    ids = [ln["id"] for ln in sample]
    print(f"样本线路：{[ln['name'] for ln in sample]}")
    print(f"          官方色：{[ln['color'] for ln in sample]}")
    print(f"          两两最小色距 = {min_dist}（>3*TOL 才分得开）")

    app = QApplication.instance() or QApplication(sys.argv)
    ok = fail = 0

    def check(cond, label, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  [OK]   {label} {detail}")
        else:
            fail += 1
            print(f"  [FAIL] {label} {detail}")

    # ================= A. 收起态 =================
    print("\n=== A. 收起态（QToolButton 上逐段自绘）===")
    btns = {}
    ls = LinesSelect(lines, ids)
    ls.resize(300, 28)
    pm = ls.grab()
    img = to_rgb_image(pm)

    # ★ 自检 1：画面里得真有东西（渲染失败 → 画布原样返回 → 断言永远通过）
    non_white = sum(1 for y in range(img.height()) for x in range(img.width())
                    if img.pixelColor(x, y) != QColor(Qt.white))
    check(non_white > 200, "画面非空自绘", f"非白像素={non_white}")

    # ★ 自检 2： old default single-color path must NOT be used
    check(ls.text() != "", "仍保留纯文本接口", f"text={ls.text()!r}")
    segs = getattr(ls, "_segs", None)
    check(isinstance(segs, list) and len(segs) == len(ids),
          "已构造分段数据", f"len={len(segs or [])}")

    prev_cx = -1.0
    for ln in sample:
        tgt = hex2rgb(ln["color"])
        n, cx, cy = count_color(img, tgt)
        check(n >= MIN_PX, f"{ln['name']} 本色像素数", f"{n} >= {MIN_PX}")
        check(cx > prev_cx, f"{ln['name']} 质心 x 递增", f"{cx:.1f} > {prev_cx:.1f}")
        prev_cx = cx

    # ★ A6 本征判据：把颜色整体轮转一位。
    #   为什么不用"数别的线路色有没有混进来"：① 各段字数不同，绝对数量没有可比性；
    #     ② AA 边缘是灰的，浅色线路（如 20 号线 #99DBDE）会被灰边误命中。
    #   正解是**相对判据**：既然是一段一色，把配色方案轮转一位后，
    #   每种颜色必须整体挪到别的位置 —— 单一颜色的实现则纹丝不动。
    print("  -- A6 颜色轮转一位：每种颜色都必须整体搬家 --")
    rot = {}
    for i, ln in enumerate(sample):
        rot[ln["id"]] = sample[(i + 1) % len(sample)]["color"]
    orig_color_fn = W.line_text_color          # ★ 用完必须还原，否则污染 B/C 组
    W.line_text_color = lambda ln, _m=rot: _m.get((ln or {}).get("id"),
                                                  LINE_TEXT_FALLBACK)
    ls._refresh_text()
    ls.update()
    img2 = to_rgb_image(ls.grab())
    for ln in sample:
        _n1, cx1, _y1 = count_color(img, hex2rgb(ln["color"]))
        _n2, cx2, _y2 = count_color(img2, hex2rgb(ln["color"]))
        shift = abs(cx1 - cx2)
        check(shift >= 20.0, f"{ln['name']} 颜色轮转后质心位移",
              f"|{cx1:.1f} - {cx2:.1f}| = {shift:.1f} >= 20")
    W.line_text_color = orig_color_fn          # ★ 还原
    ls._refresh_text()

    # ================= B. 展开态候选 =================
    print("\n=== B. 展开态（LinesPopup 里每个勾选框）===")
    pop = LinesPopup(lines)
    pop.adjustSize()
    pop.layout().activate()
    checked = 0
    for ln in sample:
        cb = pop.checks.get(ln["id"])
        check(cb is not None, f"{ln['name']} 候选存在", "")
        if cb is None:
            continue
        cpm = cb.grab()
        check(cpm.width() > 10 and cpm.height() > 8,
              f"{ln['name']} 勾选框有尺寸", f"{cpm.width()}x{cpm.height()}")
        cimg = to_rgb_image(cpm)
        n, cx, cy = count_color(cimg, hex2rgb(ln["color"]))
        check(n >= MIN_PX, f"{ln['name']} 候选文字用官方色", f"像素={n}")
        checked += 1

    # 展开态与收起态取色必须一致（同一份 lines.json，不是两份手抄）
    print("\n=== C. 两处取色同源 ===")
    allrgb = [str(ln.get("color", "")) for ln in lines]
    bad = [c for c in allrgb if not c.startswith("#")]
    check(not bad, "所有线路都有官方色 hex", f"缺={bad}")
    fallback_used = [ln["name"] for ln in lines
                     if W.line_text_color(ln) == LINE_TEXT_FALLBACK]
    check(not fallback_used, "无线路退化到默认灰", f"退化={fallback_used}")

    print(f"\n{'=' * 56}")
    if args.mutate_plain:
        print(f"【变异模式】应出现失败。实际：OK={ok} FAIL={fail}")
        print("结论：", "判据有效（变异被抓到）" if fail > 0
              else "!! 判据失效 —— 变异看不出差别，别信这份报告")
        return 0 if fail > 0 else 1
    print(f"【正常模式】OK={ok} FAIL={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
