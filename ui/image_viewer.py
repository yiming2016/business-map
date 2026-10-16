# -*- coding: utf-8 -*-
"""
ui/image_viewer.py
========================
站点图片**大图查看器**（v2.6.79）。

用法：
    from ui.image_viewer import show_image_viewer
    show_image_viewer(parent, path)

· 模态、无边框、圆角靠底色即可（不做透明抠角，避免 Windows 合成坑）；
· 图片等比缩到屏幕可用区域的 85% 以内（SmoothTransformation）；
· 单击图片任意处或按 Esc 关闭 —— 大图就是个"看一眼"的界面，不需要按钮。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QWidget,
)


def show_image_viewer(parent, path) -> None:
    """弹出大图查看器。path 为图片绝对路径（Path 或 str 均可）。"""
    p = Path(str(path))
    if not p.exists():
        return
    pm = QPixmap(str(p))
    if pm.isNull():
        return

    scr = QApplication.primaryScreen()
    area = scr.availableGeometry() if scr else None
    max_w = int(area.width() * 0.85) if area else 1200
    max_h = int(area.height() * 0.85) if area else 900
    if pm.width() > max_w or pm.height() > max_h:
        pm = pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    dlg = QDialog(parent)
    dlg.setModal(True)
    dlg.setWindowTitle("查看图片")
    dlg.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    dlg.setAttribute(Qt.WA_TranslucentBackground, True)

    # 圆角白底卡片，图片留 6px 边
    card = QWidget()
    card.setStyleSheet("background:#ffffff; border-radius: 10px;")
    lab = QLabel()
    lab.setPixmap(pm)          # 大图不裁圆角，保持原图观感
    lab.setFixedSize(pm.width(), pm.height())
    lay = QHBoxLayout(card)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.addWidget(lab)

    outer = QHBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(card)

    def _close(*_a) -> None:
        dlg.accept()

    lab.mousePressEvent = _close
    card.mousePressEvent = _close
    dlg.mousePressEvent = _close
    dlg.exec()
