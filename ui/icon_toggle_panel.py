"""
ui/icon_toggle_panel.py
========================
主图右上角「图标显示开关」浮层（v2.6.75）。

挂缩放面板（ScalePanel）下方。四个类别按钮：商场 / 交通 / 酒店 / 豪宅。
  · **左键单击**：整类开/关（关掉的类别图标在主图上全部隐藏）；
  · **鼠标右键**：弹出该类别下的等级菜单（商场/酒店/豪宅=红金紫绿四级，
    交通=高铁站/机场），单击某一等级可单独开/关它。
状态由 MapView 持久化到 view_settings.json（icon_visibility 键）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QMenu,
)

from ui.metro_render import (
    ICON_CATEGORIES, icon_pixmap, level_label,
)

BTN_CSS = """
QPushButton#IconCatBtn {
    background: rgba(35, 38, 46, 235);
    color: #ECEFF1;
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 12px;
}
QPushButton#IconCatBtn:checked {
    border: 1px solid #4FC3F7;
}
QPushButton#IconCatBtn:!checked {
    color: #78909C;
    background: rgba(55, 58, 66, 180);
    font-strikeout: true;
}
"""

# 类别关掉时按钮文字上加删除线（样式表 font-strikeout 不可靠，用符号兜底）
_OFF_MARK = " ⃠"


class IconTogglePanel(QWidget):
    """四类别图标开关浮层。visibility_changed(cat_on, level_on) 每次变化发全量状态。"""

    visibility_changed = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("IconTogglePanel")
        self.setStyleSheet(BTN_CSS)
        self.setToolTip("图标显示开关：左键=整类开关；右键=按等级开关")

        self._cat_on: dict = {}     # 类别键 -> bool
        self._level_on: dict = {}   # 图标键 -> bool
        self._btns: dict = {}       # 类别键 -> QPushButton

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for cat, name, emoji, _levels in ICON_CATEGORIES:
            b = QPushButton(f"{emoji} {name}")
            b.setObjectName("IconCatBtn")
            b.setCheckable(True)
            b.setChecked(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.clicked.connect(lambda on, c=cat: self._toggle_cat(c, on))
            b.customContextMenuRequested.connect(
                lambda _pos, c=cat: self._show_level_menu(c))
            self._cat_on[cat] = True
            self._btns[cat] = b
            h.addWidget(b, 0, Qt.AlignVCenter)
        h.addStretch(1)

    # ------------------------------------------------------------ 状态
    def state(self) -> tuple:
        """(cat_on, level_on) —— 给 view_settings.json 持久化用。"""
        return dict(self._cat_on), dict(self._level_on)

    def set_state(self, cat_on: dict, level_on: dict) -> None:
        """读回持久化状态（不发光信号、不刷新地图 —— 调用方负责）。"""
        self._cat_on.update(cat_on or {})
        self._level_on.update(level_on or {})
        for cat, b in self._btns.items():
            b.setChecked(bool(self._cat_on.get(cat, True)))

    # ------------------------------------------------------------ 交互
    def _toggle_cat(self, cat: str, on: bool) -> None:
        self._cat_on[cat] = bool(on)
        self.visibility_changed.emit(dict(self._cat_on), dict(self._level_on))

    def _show_level_menu(self, cat: str) -> None:
        cat_def = next((c for c in ICON_CATEGORIES if c[0] == cat), None)
        if cat_def is None:
            return
        _cat, _name, _emoji, levels = cat_def
        m = QMenu(self)
        for k in levels:
            act = m.addAction(level_label(k))
            act.setCheckable(True)
            act.setChecked(bool(self._level_on.get(k, True)))
            pm = icon_pixmap(k, 24)
            if pm is not None and not pm.isNull():
                act.setIcon(QIcon(pm))
            act.triggered.connect(
                lambda _=False, key=k: self._toggle_level(key))
        m.exec(self._btns[cat].mapToGlobal(
            self._btns[cat].rect().bottomLeft()))

    def _toggle_level(self, key: str) -> None:
        self._level_on[key] = not self._level_on.get(key, True)
        self.visibility_changed.emit(dict(self._cat_on), dict(self._level_on))
