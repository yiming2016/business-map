# -*- coding: utf-8 -*-
"""★ v2.7.14「看图模式」：把整张矢量图**烘成一张超清位图**。

用户原话：「编辑完成后可以把整张图存为图片，在非编辑模式下可以和查看图片
一样丝滑，因为矢量图优化了很多次都是卡顿」。

为什么卡：编辑模式下每个站点 / 每条线 / 每个站名都是独立矢量图元，
画面一动就要把 383 站 + 20 线 + 全部站名**重新算一遍、重新画一遍**。
看图模式先把它们**一次性画到一张大位图**上，之后的缩放 / 拖动只是
"拉照片" —— 跟看图软件一个道理。

出图密度 = 最大缩放档（0.69 像素 / 场景单位）⇒ 放到最细的一档也不糊
（用户选项③ A：整图出一张超清大图）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsItem

BG_COLOR = QColor("#F7F9FB")

# 出图密度（像素 / 场景单位）—— 与最大缩放档一致，保证放大到最细不糊。
PX_PER_UNIT = 0.69

DEFAULT_SETTINGS = {
    # 切到看图模式时自动生成图片（关掉 = 手动点齿轮里的"立即重新生成"）
    "auto_on_enter": True,
    # 每隔 N 分钟自动重新生成并保存（0 = 关）
    "interval_min": 0,
    # 退出程序前问一句"要不要保存为图片"
    "ask_on_exit": True,
    # 存盘路径（空 = 默认 <程序目录>/导出/深圳地铁图.png）
    "png_path": "",
    # 启动后自动进一次看图模式（有缓存 ⇒ 秒进，不用点按钮）。
    # ★ v2.7.17 起默认**开**：用户原话「每次进入都要点击…生成图片」的
    #   另一半就是"开软件还得点一下按钮"。配合内容-md5 缓存，第二次起
    #   是读盘不是烘图，不会白等。
    #   ★ 回归脚本要屏蔽它：设环境变量 METROEDITOR_NO_VIEW_START=1。
    "auto_on_start": True,
    # ★ v2.7.18：右侧「站点详情」面板的**默认宽度**（px）。
    #   手动拖边缘改宽会写回这里 ⇒ 下次开软件还是你拖的那个宽度。
    #   真正显示时还会按 360(最窄) / min(780, 屏宽55%)(最宽) 限幅。
    "info_panel_w": 520,
    # ★ v2.7.20：拖动留白（场景单位，1.0 倍下 ≈ px）—— 拖地图时视口边缘最多
    #   贴到"所有元素最外边界 ± 这个值"的位置。0 = 元素可贴屏幕边；越大留白越多。
    #   （对应 map_view.PAN_ELEMENT_PAD 的默认 60，见那里注释。）
    "pan_pad_scene": 24,
}


# ----------------------------------------------------------------------
# 设置
# ----------------------------------------------------------------------
def load_settings(data_dir) -> dict:
    """读 view_settings.json 里的 image_mode 段（缺的字段用默认值补）。"""
    out = dict(DEFAULT_SETTINGS)
    try:
        p = Path(data_dir) / "view_settings.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            sec = d.get("image_mode") or {}
            for k in DEFAULT_SETTINGS:
                if k in sec:
                    out[k] = sec[k]
    except Exception as e:
        print("[image_mode] 读设置失败：", repr(e))
    return out


def save_settings(data_dir, sec: dict) -> None:
    """把 image_mode 段写回 view_settings.json（**只改这一段**，别的一字不动）。"""
    try:
        p = Path(data_dir) / "view_settings.json"
        d = {}
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                d = {}
        d["image_mode"] = dict(sec)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("[image_mode] 写设置失败：", repr(e))


def default_png_path(data_dir) -> str:
    """默认存盘路径：<data 目录>/导出/深圳地铁图.png"""
    return str(Path(data_dir) / "导出" / "深圳地铁图.png")


def png_path(data_dir, sec: dict) -> str:
    return sec.get("png_path") or default_png_path(data_dir)


# ----------------------------------------------------------------------
# 缓存（不然每次开软件都要重烘一遍，白等几秒）
# ----------------------------------------------------------------------
def signature(data_dir) -> str:
    """数据"指纹"：stations.json / lines.json 的**文件内容 md5**。

    ★★ v2.7.17：以前用的是 **修改时间 + 大小**，那是错的 ——
      软件每次退出都会 `dm.save()` 无条件重写这两个文件（`closeEvent`），
      哪怕用户一个字没改，mtime 也变了 ⇒ 指纹每次都对不上 ⇒
      **缓存永远不命中**，于是"每次进来都要重新生成图片"（用户原话）。
      实测铁证：`lines.json` 与它上次退出时的 `.bak` 内容 md5 完全相同，
      但 mtime_ns 从 …973563300 变成了 …708235639200。

      改成**内容哈希**后：内容没变 ⇒ 指纹不变 ⇒ 直接读上次那张（秒进）；
      内容真变了（改了站点/线路）⇒ 指纹变 ⇒ 才重烘。
    """
    parts = []
    for name in ("stations.json", "lines.json"):
        p = Path(data_dir) / name
        try:
            h = hashlib.md5()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            parts.append(f"{name}:{h.hexdigest()}")
        except Exception:
            parts.append(f"{name}:missing")
    return "|".join(parts)


def _cache_paths(data_dir):
    d = Path(data_dir)
    return d / "_view_image.png", d / "_view_image_meta.json"


def load_cache(data_dir, sig: str, px: float):
    """缓存命中就返回 QImage，否则 None（meta 里的指纹/密度对不上也算不中）。"""
    img_p, meta_p = _cache_paths(data_dir)
    if not img_p.exists() or not meta_p.exists():
        return None
    try:
        m = json.loads(meta_p.read_text(encoding="utf-8"))
        if m.get("sig") != sig or abs(float(m.get("px", 0)) - px) > 1e-6:
            return None
        img = QImage(str(img_p))
        if img.isNull():
            return None
        return img, (m.get("x"), m.get("y"), m.get("w"), m.get("h"))
    except Exception as e:
        print("[image_mode] 读缓存失败：", repr(e))
        return None


def save_cache(data_dir, sig: str, px: float, img: QImage, rect: QRectF) -> None:
    """烘好的图存一份到 data 目录，下次开软件直接读（省一次几秒的烘图）。"""
    try:
        img_p, meta_p = _cache_paths(data_dir)
        ok = img.save(str(img_p), "PNG")
        if not ok:
            print("[image_mode] 缓存图存盘失败")
            return
        meta_p.write_text(json.dumps({
            "sig": sig, "px": px,
            "x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height(),
        }, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("[image_mode] 写缓存失败：", repr(e))


def save_png(img: QImage, path: str) -> bool:
    """把图存成 png 给用户拿去用（用户选项① C：内部快照 + 落盘都要）。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        ok = img.save(str(p), "PNG")
        if not ok:
            print("[image_mode] png 存盘失败：", path)
        return bool(ok)
    except Exception as e:
        print("[image_mode] png 存盘异常：", repr(e))
        return False


# ----------------------------------------------------------------------
# 烘图
# ----------------------------------------------------------------------
def render_view_image(view, px: float = PX_PER_UNIT):
    """把 view 的整张矢量图烘成一张位图。返回 (QImage, 源场景 rect)。

    ★ 两个必须做的临时动作（做完一定还原）：
      ① `view._scale = px` —— 站名字号是"按当前缩放档算"的，不临时设成
         出图密度的话，烘出来的字就是"缩略图上的小字"，放大后会糊。
      ② 站名 label 全部强制显示 —— 平时按缩放档隐藏了一批站名，不强制
         打开的话烘出来的图**缺字**（而且看图模式下字是图片的一部分，
         之后再也补不回来）。
    """
    # 看图模式下所有图元是藏着的，烘图前先放出来
    if getattr(view, "_view_mode", False):
        try:
            view._restore_vector_items()
        except Exception:
            pass

    # ★★ v2.7.33：看图模式下**重新烘图**时，上一张位图还在场景里没摘掉。
    #   不先把它藏起来，新图就会把旧图整张"印"上去 —— 挪过/删过的站点、线路
    #   以残影留在新 png 和缓存里（定时出图、⚙️里"立即生成"都会踩，用户改完
    #   站点重烘后看图还是旧的）。烘完把可见性还原，摘除交给 enter_view_mode。
    old_item = getattr(view, "_view_item", None)
    old_item_was_vis = None
    if old_item is not None:
        try:
            old_item_was_vis = bool(old_item.isVisible())
            if old_item_was_vis:
                old_item.setVisible(False)
        except Exception:
            old_item, old_item_was_vis = None, None

    base = view._elements_rect(force=True)
    if base is None or base.isEmpty():
        return None, None
    pad = 120.0
    rect = base.adjusted(-pad, -pad, pad, pad)

    w = int(min(rect.width() * px, 16000))
    h = int(min(rect.height() * px, 16000))
    if w < 2 or h < 2:
        return None, None

    old_scale = getattr(view, "_scale", None)
    # ② 站名强制全显示，烘完恢复
    shown = []
    try:
        for it in getattr(view, "station_items", {}).values():
            lab = getattr(it, "label", None)
            if lab is not None and not lab.isVisible():
                lab.setVisible(True)
                shown.append(lab)
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(BG_COLOR)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        try:
            view._scale = px
            view.scene_.render(p, QRectF(0, 0, w, h), rect)
        finally:
            p.end()
    finally:
        if old_scale is not None:
            view._scale = old_scale
        for lab in shown:
            try:
                lab.setVisible(False)
            except Exception:
                pass
        # ★ v2.7.33：把烘图前藏起来的旧位图恢复回去（本次烘出的图里没有它）
        if old_item is not None and old_item_was_vis:
            try:
                old_item.setVisible(True)
            except Exception:
                pass
    return img, rect


class ViewImageItem(QGraphicsItem):
    """看图模式下场景里唯一在画的图元：那张烘好的大位图。"""

    def __init__(self, pixmap: QPixmap, rect: QRectF):
        super().__init__()
        self.pix = pixmap
        self._rect = QRectF(0.0, 0.0, rect.width(), rect.height())
        self.setPos(rect.topLeft())
        self.setZValue(-100000.0)          # 垫在最底下（虽然别的都藏了）
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)   # 不吃鼠标，命中全靠坐标反查

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self._rect, self.pix, QRectF(self.pix.rect()))
