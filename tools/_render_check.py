# -*- coding: utf-8 -*-
"""只读：用**真实的渲染类**把地图局部画成 PNG，便于与原图并排对照。

用法: python tools/_render_check.py <cx> <cy> <half> [viewscale] [outscale]
  viewscale = 程序的"视图缩放"（决定圆点/药丸相对地图的大小）
  outscale  = 出图放大倍数（只是把正确画面放大，不改变观感）
★ 想和原图 1:1 对比就传 viewscale=0.54（此时原图 26 像素宽的药丸恰好也是 26 场景像素）。
产物: logs/_render_check.png（上=我们的渲染，下=原图同一区域）
"""
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC_ROOT))

from PySide6.QtWidgets import QApplication, QGraphicsScene  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor          # noqa: E402
from PySide6.QtCore import QRectF, QPointF                  # noqa: E402

from core.data_manager import get_data_manager      # noqa: E402
from ui.metro_render import MetroLineItem, StationDotItem   # noqa: E402
from ui.map_view import (build_line_points_ex, build_link_items, apply_through_links,
                         declutter_link_labels, LINK_LABEL_PAD)   # noqa: E402

from PIL import Image, ImageDraw, ImageFont          # noqa: E402

def _argf(idx, default):
    """安全取浮点参数（multi 模式下 argv 里是站名，不能直接 float）。"""
    try:
        return float(sys.argv[idx])
    except (IndexError, ValueError):
        return default


SCALE = _argf(4, 1.6)
OUT = _argf(5, 1.0)


def build():
    dm = get_data_manager()
    stations = dm.all_stations()
    lines = dm.all_lines()
    scene = QGraphicsScene()
    through = [(d["a"], d["b"]) for d in (dm.stations_doc.get("through_links") or [])
               if d.get("a") and d.get("b")]
    for line in lines:
        lid = str(line["id"])
        # ★ 与 ui/map_view.rebuild_lines 共用同一段建点逻辑（含贯通连接）
        seq = apply_through_links(line.get("stations") or [], through)
        pts, ebl = build_line_points_ex(lid, seq, stations)
        if len(pts) < 2:
            continue
        it = MetroLineItem(lid, line.get("color", "#888888"))
        it.set_points(pts, smooth=True, elbows=ebl)
        it.apply_view_scale(SCALE)
        scene.addItem(it)
    color_of = {}
    for line in lines:
        for nm in (line.get("stations") or []):
            color_of.setdefault(nm, line.get("color", "#444444"))
    dots = []
    for nm, st in stations.items():
        if nm not in color_of:
            continue
        dot = StationDotItem(nm, st, QColor(color_of[nm]))
        dot.apply_view_scale(SCALE)
        dot.set_label_visible(False)
        scene.addItem(dot)
        dots.append(dot)
    # ★ v2.6.21：虚线 + 同名副站体也走**同一段构建代码**（否则对照图看不到它们）
    dashes, alts = build_link_items(
        stations, dm.stations_doc.get("transfer_links"),
        lambda lid: QColor(dm.line_color(lid)), SCALE)
    for it in dashes:
        scene.addItem(it)
    for _k, dot in alts:
        dot.set_label_visible(False)
        scene.addItem(dot)
        dots.append(dot)
    # ★ v2.6.24：线路末端的线路号方块也走**同一段构建代码**
    from ui.metro_render import TerminalBadgeItem                     # noqa: E402
    from ui.map_view import build_terminal_badge_specs               # noqa: E402
    for _key, lid, x, y, ux, uy, dist, lane in build_terminal_badge_specs(stations, lines):
        bd = TerminalBadgeItem(lid, QColor(dm.line_color(lid)))
        bd.set_layout(x, y, ux, uy, dist, lane)
        bd.apply_view_scale(SCALE)
        scene.addItem(bd)
    # ★ v2.6.22："约XX米"的摆位也要跟程序一致 —— 共用 declutter_link_labels，
    #   否则"工具里看着不叠、软件里叠成一坨"。站名在这张对照图里是全隐藏的，
    #   所以只剩"避站点圆点 + 避线路 + 米数之间互避"三件事。
    from ui.metro_render import LineSegIndex, line_screen_width   # noqa: E402
    _k = 1.0 / max(SCALE, 0.01)
    idx = LineSegIndex()
    # ★ build() 收的是 **dict**（内部 .values()），键随便给，只要唯一
    idx.build({str(i): it for i, it in enumerate(scene.items())
               if it.__class__.__name__ == "MetroLineItem"},
              80.0, 0)
    declutter_link_labels(
        dashes, dots, idx,
        (line_screen_width(SCALE) * 0.5 + 1.5) * _k,
        LINK_LABEL_PAD * _k)
    return scene


from PySide6.QtWidgets import QGraphicsScene   # noqa: E402


def main():
    # ★ multi 模式：python tools/_render_check.py multi <outscale> 站1 站2 ...
    #   一次把多个站拼成"我们的渲染 / 原图"上下对照的大图，方便一眼验收。
    if len(sys.argv) > 1 and sys.argv[1] == "multi":
        multi()
        return
    cx, cy = int(sys.argv[1]), int(sys.argv[2])
    half = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    app = QApplication(sys.argv)   # noqa: F841
    scene = build()
    size = int(half * 2 * SCALE * OUT)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    scene.render(p, QRectF(0, 0, size, size), QRectF(cx - half, cy - half, half * 2, half * 2))
    p.end()
    img.save(str(SRC_ROOT / "logs" / "_render_check_raw.png"))

    mine = Image.open(SRC_ROOT / "logs" / "_render_check_raw.png").convert("RGB")
    orig = Image.open(SRC_ROOT / "assets/shenzhen_metro.png").convert("RGB").crop(
        (cx - half, cy - half, cx + half, cy + half)).resize(mine.size, Image.LANCZOS)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
    except Exception:
        font = ImageFont.load_default()
    title = 32
    sheet = Image.new("RGB", (mine.width, mine.height * 2 + title * 2 + 6), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((6, 4), "我们的渲染", fill=(20, 20, 20), font=font)
    sheet.paste(mine, (0, title))
    d.text((6, title + mine.height + 4), "原图", fill=(20, 20, 20), font=font)
    sheet.paste(orig, (0, title * 2 + mine.height + 6))
    sheet.save(SRC_ROOT / "logs" / "_render_check.png")
    print("saved", sheet.size)


def multi():
    """把多个换乘站拼成一张上下对照图：上排=我们的渲染，下排=原图同区域。"""
    from core.data_manager import get_data_manager
    out_scale = float(sys.argv[2]) if len(sys.argv) > 2 else 2.2
    names = sys.argv[3:]
    app = QApplication(sys.argv)   # noqa: F841
    # ★ 图元的"屏幕尺寸"要按**有效视图缩放**来定：出图是把 (2×HALF) 场景单位
    #   映射到 TILE 像素 ⇒ 有效缩放 = TILE / (2×HALF) = VS × out_scale。
    #   漏了这一步，药丸/线宽会被画成 0.67 倍小一号的（第一版就是这个错）。
    globals()["SCALE"] = 0.54 * out_scale
    scene = build()
    dm = get_data_manager()
    st = dm.all_stations()
    HALF, VS = 165, 0.54
    TILE = int(HALF * 2 * VS * out_scale)
    try:
        fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    except Exception:
        fnt = ImageFont.load_default()
    orig_img = Image.open(SRC_ROOT / "assets/shenzhen_metro.png").convert("RGB")
    tiles_m, tiles_o = [], []
    for nm in names:
        s = st.get(nm)
        if not s:
            continue
        cx, cy = int(float(s["x"])), int(float(s["y"]))
        img = QImage(TILE, TILE, QImage.Format_ARGB32)
        img.fill(QColor("#FFFFFF"))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        scene.render(p, QRectF(0, 0, TILE, TILE),
                     QRectF(cx - HALF, cy - HALF, HALF * 2, HALF * 2))
        p.end()
        img.save(str(SRC_ROOT / "logs" / "_multi_tmp.png"))
        tiles_m.append(Image.open(SRC_ROOT / "logs" / "_multi_tmp.png").convert("RGB"))
        tiles_o.append(orig_img.crop((cx - HALF, cy - HALF, cx + HALF, cy + HALF))
                       .resize((TILE, TILE), Image.LANCZOS))
    n = len(tiles_m)
    PAD, LBL = 8, 24
    W = n * TILE + (n + 1) * PAD
    H = 2 * (TILE + LBL) + 3 * PAD
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 4), "我们的渲染", fill=(10, 10, 10), font=fnt)
    d.text((PAD, TILE + LBL + 2 * PAD), "原图", fill=(10, 10, 10), font=fnt)
    for i in range(n):
        x = PAD + i * (TILE + PAD)
        sheet.paste(tiles_m[i], (x, LBL))
        d.text((x + 2, LBL + TILE), names[i], fill=(10, 10, 10), font=fnt)
        sheet.paste(tiles_o[i], (x, LBL + TILE + LBL + 2 * PAD))
    sheet.save(SRC_ROOT / "logs" / "_render_compare_sheet.png")
    print("saved", sheet.size, n)


if __name__ == "__main__":
    main()
