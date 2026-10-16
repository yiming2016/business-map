# -*- coding: utf-8 -*-
"""给"悬浮提示 + 封面图"截图。

真实走一遍 data/covers/ 的读写（不写 stations.json），截完自动清理。

用法：
    python tools/_shot_tooltip.py             # 带封面
    python tools/_shot_tooltip.py --no-cover  # 不带封面（对照组）
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication                       # noqa: E402
from PySide6.QtGui import QPixmap, QColor, QPainter, QLinearGradient, QBrush  # noqa: E402
from PySide6.QtCore import Qt, QTimer, QPoint                     # noqa: E402

from core.data_manager import get_data_manager                    # noqa: E402
from ui.tooltip import HoverTip                                   # noqa: E402

no_cover = "--no-cover" in sys.argv
out = SRC / ("_v247_tip_nocover.png" if no_cover else "_v247_tip.png")

app = QApplication(sys.argv)
dm = get_data_manager()

# 造一张像样的示例封面（渐变 + 站名块），免得截图里是一块纯色
demo_src = SRC / "_demo_cover.png"
pm = QPixmap(640, 400)
g = QLinearGradient(0, 0, 640, 400)
g.setColorAt(0.0, QColor("#0d47a1"))
g.setColorAt(1.0, QColor("#4dd0e1"))
p = QPainter(pm)
p.fillRect(0, 0, 640, 400, QBrush(g))
p.setBrush(QColor(255, 255, 255, 210))
p.setPen(Qt.NoPen)
p.drawRoundedRect(40, 130, 560, 140, 16, 16)
p.end()
pm.save(str(demo_src))

cover_file = ""
if not no_cover:
    cover_file = dm.import_cover("__tooltip_demo__", str(demo_src))

data = {
    "station_name": "机场东",
    "lines": ["1", "11", "12"],
    "is_transfer": True,
    "description": "深圳宝安国际机场东侧，1/11/12 号线换乘枢纽，紧邻 T3 航站楼。",
    "cover": cover_file,
}

tip = HoverTip()
tip.show_for(QPoint(200, 200), data, dm.resolve_cover(data))


def shoot():
    app.processEvents()
    grab = tip.grab()
    grab.save(str(out))
    print(f"[OK] {out}  ({grab.width()}x{grab.height()})  cover={cover_file!r}")

    # ★ grab() 对 Qt.ToolTip 这类顶级窗口不会还原样式表底板，
    #   所以再真抓一次屏幕，用来看"显示在桌面上"的真实样子。
    scr = app.primaryScreen()
    shot = scr.grabWindow(0, tip.x() - 10, tip.y() - 10,
                          tip.width() + 20, tip.height() + 20)
    screen_out = SRC / ("_v247_tip_screen_nocover.png" if no_cover else "_v247_tip_screen.png")
    shot.save(str(screen_out))
    print(f"[OK] 真·抓屏 {screen_out}  ({shot.width()}x{shot.height()})")

    # ★ 用像素值判断底板到底有没有画出来（肉眼容易误判）
    # 抓屏区域比 tooltip 四周各多 10px，所以卡片内部 = 抓屏坐标 10~w-10
    img = shot.toImage()
    w, h = img.width(), img.height()
    probes = [(w - 20, 25), (20, h - 20), (w - 20, h - 20)]
    print("    卡片内部像素（应该接近 35,35,40 才算底板画出来了）:")
    for (px, py) in probes:
        c = img.pixelColor(max(0, px), max(0, py)).getRgb()
        print(f"      ({px},{py}) -> {c}")

    tip.hide()
    app.processEvents()
    # 清理
    if cover_file:
        dm.remove_cover(cover_file)
    if demo_src.exists():
        demo_src.unlink()
    left = list(dm.covers_dir().glob("__tooltip_demo__*"))
    print("残留:", [q.name for q in left] or "无")
    app.quit()


QTimer.singleShot(500, shoot)
sys.exit(app.exec())
