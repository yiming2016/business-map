# -*- coding: utf-8 -*-
"""一次性补丁：把 _chk_label_on_line.py 里「🔄 旋转箭头环」的判据
整段换成 v2.6.19「大药丸」的判据（按行号替换，避免长文本匹配出错）。
"""
import io

P = "C:/software/subway/源码/tools/_chk_label_on_line.py"
src = io.open(P, encoding="utf-8").read().split("\n")
assert "===== B 换乘站专属图标" in src[305], src[305][:60]
assert "===== C 不许因避让线路" in src[434], src[434][:60]

NEW = r'''    print("\n===== B 换乘站图标（大药丸 v2.6.19，像素可量）=====")
    RX, RY = MR.SCREEN_TRANSFER_RX, MR.SCREEN_TRANSFER_RY
    at_tr, bg = icon_pixels(True)
    at_nm, _bg2 = icon_pixels(False)
    dark = QColor(TRANSFER_RING_COLOR)
    print("      药丸尺（屏幕px）：半宽 %.1f | 半高 %.1f | 高/宽 %.2f"
          % (RX, RY, RY / RX))

    # ① 竖向：垂直方向（90°）在「超过水平半宽」之后仍然有图标 ⇒ 药丸是竖着长的
    #    ★ 判据不依赖角度约定：同一半径放在 0°（水平）就该是背景，放 90° 不是。
    c_up = at_tr(RX + 4.0, 90)
    check("药丸是**竖向**的：垂直方向 r=半宽+4（%.1f）仍不是背景" % (RX + 4.0),
          dist(c_up, bg) > 60, f"{c_up.name()} vs 底 {bg.name()}")
    c_side = at_tr(RX + 4.0, 0)
    check("同一半径放**水平**方向（0°）已是背景 ⇒ 确实只朝上下长",
          dist(c_side, bg) < 60, f"{c_side.name()}")

    # ② 水平方向边界清晰（没糊成一坨）
    check("水平方向 r=半宽-1 仍在图标内",
          dist(at_tr(RX - 1.0, 0), bg) > 60, f"{at_tr(RX - 1.0, 0).name()}")
    check("水平方向 r=半宽+3 已在图标外",
          dist(at_tr(RX + 3.0, 0), bg) < 60, f"{at_tr(RX + 3.0, 0).name()}")

    # ③ 侧边深色描边
    check("药丸侧边（r=半宽, 0°）是**深色描边**",
          dist(at_tr(RX, 0), dark) < 220, f"{at_tr(RX, 0).name()}")

    # ④ 中心仍是线路色小点（换乘站压多条线，用它表明主色）
    check("中心是**线路色**实心点（示例 #1565C0）",
          dist(at_tr(0), QColor("#1565C0")) < 90, f"{at_tr(0).name()}")

    # ⑤ 比普通站明显更大
    check("换乘站比普通站**更大**（缩到最小也能靠尺寸先看出来）",
          RY > SCREEN_NORMAL_R * 2, f"半高 {RY} > 普通站半径 {SCREEN_NORMAL_R}×2")

    # ⑥ 两种图标在同一位置颜色不同（可区分）
    check("同一位置普通站与换乘站颜色明显不同（两种图标可区分）",
          dist(at_nm(RX + 4.0, 90), c_up) > 100,
          f"普通 {at_nm(RX + 4.0, 90).name()} vs 换乘 {c_up.name()}")

    print("\n===== B2 变异自检：把药丸改回正圆 ⇒ 「竖向」判据必须失败 =====")
    # ★★ 只能换**实例所属类的方法**；还原时赋回原函数即可（这里是普通函数，
    #    不是 staticmethod，直接赋回去就是普通方法 —— 与旧代码的坑不同）。
    old_pill = MR.StationDotItem._paint_transfer_pill

    def _round_style(self, painter, RX_, RY_, k):
        """变异体：画**正圆**（半径只取半宽）⇒ 垂直方向不再长出药丸。"""
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        pen = QPen(QColor(TRANSFER_RING_COLOR))
        pen.setWidthF(MR.SCREEN_DOT_STROKE * k)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), RX_, RX_)

    MR.StationDotItem._paint_transfer_pill = _round_style
    at_old, _ = icon_pixels(True)
    c_old = at_old(RX + 4.0, 90)
    check("变异（改成正圆）后垂直方向 r=半宽+4 变回背景 ⇒ 判据真在上岗",
          dist(c_old, bg) < 60, f"变异后 {c_old.name()}")
    MR.StationDotItem._paint_transfer_pill = old_pill

    # 变异 2：不换画法，只把半高砍到等于半宽（抓「RY 常量真的在起作用」）
    old_ry = MR.SCREEN_TRANSFER_RY
    MR.SCREEN_TRANSFER_RY = RX
    at_sq, _ = icon_pixels(True)
    check("变异（半高砍到=半宽）后垂直方向 r=半宽+4 变回背景 ⇒ 判据真在上岗",
          dist(at_sq(RX + 4.0, 90), bg) < 60,
          f"变异后 {at_sq(RX + 4.0, 90).name()}")
    MR.SCREEN_TRANSFER_RY = old_ry
'''.split("\n")

out = src[:305] + NEW + src[434:]
io.open(P, "w", encoding="utf-8").write("\n".join(out))
print("已替换 B 段（原第 306~434 行 → 新药丸判据），新文件行数：", len(out))
