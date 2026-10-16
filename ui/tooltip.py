"""
ui/tooltip.py
========================
悬浮提示（自定义 QWidget 当 tooltip，避开了系统 tooltip 黑框不易看的毛病）

用法：
    self.tip = HoverTip(self)
    self.tip.hide()

    def on_hover(station_id):
        data = dm.get_station(station_id)
        self.tip.show_for(pos, data, dm.resolve_images(data))

2026-09-18 新增：如果该站点设了**封面图**，先把图片显示在提示最上方。
  · 图片按 (路径, mtime) 缓存 —— 鼠标在站点上移动时每次都会触发 show_for，
    不缓存的话每帧都要读一次盘、缩放一次，会明显卡顿。
  · 只保留最近一张（同时只会显示一个站点的提示），避免缓存无限增长。

2026-10-02 v2.6.79 多图升级：
  · show_for：悬浮模式 —— 只显示**第一张**图；图片多于 1 张时提示
    「共 N 张 · 单击站点查看全部」。
  · pin_for：**固定模式** —— 单击站点后气泡钉住不消失，鼠标可以移进气泡，
    图片横向排开、下方自带横向滚动条（可拖动逐张查看），左上角计数
    「第 x / N 张」；单击任意图片弹出大图查看器（ui/image_viewer）。
  · 解除固定：鼠标按下地图空白/别的站点、按 Esc、双击进编辑弹窗 ——
    由 main_window 调 unpin()。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QPoint, QRectF, QSize
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QApplication,
    QScrollArea,
)

from ui.widgets import rounded_pixmap


COVER_W = 240
COVER_H = 150
# 固定模式的图片带：高度略高、宽度略宽，滚动条占 ~12px
PIN_IMG_H = 170
PIN_STRIP_W = 300
PIN_STRIP_H = PIN_IMG_H + 14
# 底板颜色。alpha 给满：Qt.ToolTip + WA_TranslucentBackground 在 Windows 上
# 对半透明底板的合成不可靠（实测 242 的 alpha 在屏幕上几乎全透），
# 圆角外的部分本来就 alpha=0，所以给满 alpha 一样能得到圆角卡片。
BG = QColor(35, 35, 40, 255)
BG_RADIUS = 8


class HoverTip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("HoverTip")

        # ★ 底板用 paintEvent 自己画。
        #   坑：纯 QWidget 子类**不会**绘制样式表里的 background-color
        #   （要开 WA_StyledBackground 才行，但对 Qt.ToolTip 顶级窗口仍然不可靠）。
        #   之前这里只有样式表没 paintEvent，结果提示框实际是**透明的**，
        #   桌面上的字直接透过来，浅色文字基本看不清。
        #   这里直接 setStyleSheet 只保留文字颜色，背景交给 paintEvent。
        self.setStyleSheet("""
            QLabel { color: #f1f1f1; }
            QLabel#title { color: #FFD54F; font-weight: bold; font-size: 13px; }
            QLabel#field { color: #B0BEC5; font-size: 11px; }
            QLabel#value { color: #ECEFF1; font-size: 11px; }
            QLabel#counter { color: #90CAF9; font-size: 11px; }
        """)

        # ★ v2.6.79：固定模式状态
        self._pinned = False
        self._pin_sid = ""
        self._images_meta: dict = {}      # 计数用（滚动条 valueChanged 里取不到图片列表）

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        # ---- 悬浮模式：单张封面图（没有就整块隐藏）----
        self.lbl_cover = QLabel("")
        self.lbl_cover.setObjectName("cover")
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.hide()

        # ---- 固定模式：横向图片带 + 滚动条 ----
        self.pin_scroll = QScrollArea()
        self.pin_scroll.setWidgetResizable(True)
        self.pin_scroll.setFrameShape(QFrame.NoFrame)
        self.pin_scroll.setFixedSize(PIN_STRIP_W, PIN_STRIP_H)
        self.pin_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.pin_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pin_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:horizontal { background: rgba(255,255,255,30);
                                    height: 10px; border-radius: 5px; }
            QScrollBar::handle:horizontal { background: #2F6FED; border-radius: 5px;
                                            min-width: 24px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal
                { height: 0; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal
                { background: none; }
        """)
        self.pin_host = QWidget()
        self.pin_host.setStyleSheet("background: transparent;")
        self.pin_row = QHBoxLayout(self.pin_host)
        self.pin_row.setContentsMargins(0, 0, 0, 0)
        self.pin_row.setSpacing(6)
        self.pin_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.pin_scroll.setWidget(self.pin_host)
        self.pin_scroll.hide()
        # 滚动条一动 → 计数跟着走（"第 x / N 张"）
        self.pin_scroll.horizontalScrollBar().valueChanged.connect(
            self._update_pin_counter)

        self.lbl_title = QLabel("")
        self.lbl_title.setObjectName("title")
        self.lbl_title.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))

        self.lbl_lines = QLabel("")
        self.lbl_lines.setObjectName("value")

        # ★ v2.6.90：第三段「所属区」（福田区…），与站名/线路同一行、垂直居中。
        self.lbl_district = QLabel("")
        self.lbl_district.setObjectName("value")

        # ★ v2.6.6：站名与「线路：…」**并成一排**（原来是上下两行）。
        #   用户原话：「改成『xx站点 线路：2、5』，即都显示在一行」。
        #   为什么用两个 QLabel 而不是拼成一个字符串：
        #   站名是黄色加粗 13px、线路是浅灰 11px，两种样式塞一个 QLabel
        #   就得走富文本（HTML），字号/颜色都不再受上面那条样式表管，
        #   回归里也没法用 `text()` 直接断言。两个标签放在同一 QHBoxLayout 里最稳。
        title_row = QWidget()
        h = QHBoxLayout(title_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self.lbl_title, 0, Qt.AlignVCenter)
        h.addWidget(self.lbl_lines, 0, Qt.AlignVCenter)
        h.addWidget(self.lbl_district, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self.title_row = title_row

        self.lbl_desc = QLabel("")
        self.lbl_desc.setObjectName("value")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setMaximumWidth(280)

        # 多图提示（悬浮模式且 >1 张时显示）
        self.lbl_multi = QLabel("")
        self.lbl_multi.setObjectName("counter")
        self.lbl_multi.hide()

        root.addWidget(self.lbl_cover)
        root.addWidget(self.pin_scroll)
        root.addWidget(title_row)
        root.addWidget(self.lbl_desc)
        root.addWidget(self.lbl_multi)

        # 封面缓存：(路径, mtime) -> QPixmap
        self._cover_cache: Dict[tuple, QPixmap] = {}

        self.adjustSize()

    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # ★ v2.6.90：标题行格式 =「站名 3号线、5号线 福田区」
    #   （用户原话：把「福保 线路：3」改成「福保 3号线 福田区」，
    #     三个元素同一行、文字中心水平对齐 —— AlignVCenter）
    # ------------------------------------------------------------
    def _set_lines_text(self, lines) -> None:
        lines = [str(l) for l in (lines or []) if str(l)]
        if lines:
            self.lbl_lines.setText("、".join(f"{l}号线" for l in lines))
            self.lbl_lines.show()
        else:
            self.lbl_lines.setText("")
            self.lbl_lines.hide()

    def _set_district_text(self, data: Dict) -> None:
        d = str((data or {}).get("district") or "").strip()
        if d:
            self.lbl_district.setText(d)
            self.lbl_district.show()
        else:
            self.lbl_district.setText("")
            self.lbl_district.hide()

    def paintEvent(self, event) -> None:
        """自己画圆角深色底板（样式表在 Qt.ToolTip 窗口上不可靠）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          BG_RADIUS, BG_RADIUS)
        p.end()

    # ------------------------------------------------------------
    # 固定模式（v2.6.79）
    # ------------------------------------------------------------
    @property
    def pinned(self) -> bool:
        return self._pinned

    @property
    def pinned_station_id(self) -> str:
        return self._pin_sid

    def _place(self, global_pos: QPoint) -> None:
        """默认贴在鼠标右下；**贴边时收回来**，否则加了封面图的高提示框
        在屏幕下半部分会被切掉一大截。"""
        self.adjustSize()
        w, h = self.width(), self.height()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = global_pos.x() + 14
        y = global_pos.y() + 14
        if x + w > area.right():
            x = global_pos.x() - w - 14
        if y + h > area.bottom():
            y = global_pos.y() - h - 14
        x = max(area.left(), min(x, area.right() - w))
        y = max(area.top(), min(y, area.bottom() - h))
        self.move(int(x), int(y))

    def _cover_pixmap(self, path: Optional[object]) -> QPixmap:
        if not path:
            return QPixmap()
        try:
            mtime = Path(str(path)).stat().st_mtime
        except Exception:
            return QPixmap()
        key = (str(path), mtime)
        pm = self._cover_cache.get(key)
        if pm is None:
            if len(self._cover_cache) >= 64:      # 多图后缓存要放宽一点
                self._cover_cache.clear()
            pm = rounded_pixmap(path, COVER_W, COVER_H, radius=8)
            self._cover_cache[key] = pm
        return pm

    def _pin_pixmap(self, path) -> QPixmap:
        """固定模式里的图片：按高度等比缩放（宽度自然延伸，横向滚动看全）。"""
        try:
            mtime = Path(str(path)).stat().st_mtime
        except Exception:
            mtime = 0.0
        key = ("pin", str(path), mtime, PIN_IMG_H)
        pm = self._cover_cache.get(key)
        if pm is None:
            raw = QPixmap(str(path))
            if raw.isNull():
                return QPixmap()
            pm = raw.scaledToHeight(PIN_IMG_H, Qt.SmoothTransformation)
            if len(self._cover_cache) >= 64:
                self._cover_cache.clear()
            self._cover_cache[key] = pm
        return pm

    def _update_pin_counter(self, _value: int = 0) -> None:
        """按滚动条位置估算当前在最前面的是第几张。"""
        sb = self.pin_scroll.horizontalScrollBar()
        n = max(1, self.pin_row.count() - 1)      # 末尾有 stretch
        if n <= 0 or not self._images_meta:
            return
        stride = self._images_meta.get("stride", 1) or 1
        idx = min(n, int(round(sb.value() / max(stride, 1))) + 1)
        self.lbl_multi.setText(f"第 {idx} / {n} 张 · 左右拖动查看")

    def unpin(self, hide: bool = True) -> None:
        """解除固定（回悬浮模式）。main_window 在按下地图 / Esc / 双击时调用。"""
        self._pinned = False
        self._pin_sid = ""
        if hide:
            self.hide()

    def pin_for(self, global_pos: QPoint, data: Dict,
                cover_paths: Optional[list] = None,
                station_id: str = "") -> None:
        """固定模式：图片横向排开 + 滚动条 + 点图看大图。"""
        self._pinned = True
        self._pin_sid = station_id
        paths = list(cover_paths or [])

        self.lbl_cover.hide()
        # 重建图片带
        while self.pin_row.count():
            it = self.pin_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        total_w = 0
        for p in paths:
            pm = self._pin_pixmap(p)
            if pm.isNull():
                continue
            lab = QLabel()
            lab.setPixmap(pm)
            lab.setFixedSize(pm.width(), PIN_IMG_H)
            lab.setCursor(Qt.PointingHandCursor)
            lab.setToolTip("单击查看大图")
            lab.mousePressEvent = (lambda _e, pp=p: self._open_viewer(pp))
            self.pin_row.addWidget(lab, 0, Qt.AlignVCenter)
            total_w += pm.width() + 6
        self.pin_row.addStretch(1)
        # 计数用元数据（滚动条 valueChanged 里取不到图片列表）
        first_w = 0
        if paths:
            pm0 = self._pin_pixmap(paths[0])
            first_w = pm0.width() if not pm0.isNull() else 1
        self._images_meta = {"stride": max(first_w + 6, 1)}
        self.lbl_multi.show()
        self._update_pin_counter()

        name = data.get("station_name", "未命名")
        lines = data.get("lines") or []
        desc = (data.get("description") or "").strip()
        if data.get("is_transfer"):
            name = "🔄 " + name
        self.lbl_title.setText(name)
        self._set_lines_text(lines)
        self._set_district_text(data)
        if desc:
            self.lbl_desc.setText(
                (desc[:120] + "…") if len(desc) > 120 else desc)
            self.lbl_desc.show()
        else:
            self.lbl_desc.hide()

        if paths:
            self.pin_scroll.show()
        else:
            self.pin_scroll.hide()

        self._place(global_pos)
        self.show()
        self.raise_()

    def _open_viewer(self, path) -> None:
        from ui.image_viewer import show_image_viewer
        show_image_viewer(self, path)

    # ------------------------------------------------------------
    # 悬浮模式
    # ------------------------------------------------------------
    def _apply_cover(self, cover_path: Optional[object]) -> None:
        pm = self._cover_pixmap(cover_path)
        if pm.isNull():
            self.lbl_cover.clear()
            self.lbl_cover.hide()
        else:
            self.lbl_cover.setPixmap(pm)
            self.lbl_cover.show()

    def show_for(self, global_pos: QPoint, data: Dict,
                 cover_paths: Optional[list] = None) -> None:
        """悬浮模式。cover_paths = 全部图片路径列表（只显示第一张）。"""
        # 悬浮到别的站点 ⇒ 固定状态自然解除
        self._pinned = False
        self._pin_sid = ""

        name = data.get("station_name", "未命名")
        lines = data.get("lines") or []
        desc = (data.get("description") or "").strip()

        # ★ v2.6.6：去掉 📍 定位图标（用户要求），但**换乘站的 🔄 保留**
        #   —— 它是"这站能换乘"的唯一视觉提示，删了就看不出来了。
        if data.get("is_transfer"):
            name = "🔄 " + name

        self.lbl_title.setText(name)
        self._set_lines_text(lines)
        self._set_district_text(data)
        if desc:
            short = (desc[:120] + "…") if len(desc) > 120 else desc
            self.lbl_desc.setText(short)
            self.lbl_desc.show()
        else:
            self.lbl_desc.hide()

        # 图片：只显示第一张（v2.6.79）
        self.pin_scroll.hide()
        paths = list(cover_paths or [])
        self._apply_cover(paths[0] if paths else None)
        if len(paths) > 1:
            self.lbl_multi.setText(f"共 {len(paths)} 张 · 单击站点查看全部")
            self.lbl_multi.show()
        else:
            self.lbl_multi.hide()

        self._place(global_pos)
        self.show()
        self.raise_()

    def show_minimal(self, global_pos: QPoint, station_name: str, lines=None) -> None:
        self._pinned = False
        self._pin_sid = ""
        self.lbl_cover.clear()
        self.lbl_cover.hide()
        self.pin_scroll.hide()
        self.lbl_multi.hide()
        # 与 show_for 保持一致：三段式一行、无 📍（show_minimal 没有 data ⇒ 无区）
        self.lbl_title.setText(station_name)
        self._set_lines_text(lines)
        self._set_district_text(None)
        self.lbl_desc.hide()
        self._place(global_pos)
        self.show()
        self.raise_()

    def wheelEvent(self, event) -> None:       # noqa: N802
        """固定模式下鼠标滚轮 = 横向翻图（悬浮模式没有滚动条，忽略）。"""
        if self._pinned and self.pin_scroll.isVisible():
            sb = self.pin_scroll.horizontalScrollBar()
            d = event.angleDelta().y() or event.angleDelta().x()
            if d:
                sb.setValue(sb.value() - d)     # 滚轮向上 = 往左回看
                event.accept()
                return
        event.ignore()
