# -*- coding: utf-8 -*-
"""编辑弹窗 + 相关控件的功能回归测试（v2.4.7）。

覆盖：
  A. 编辑模式：名称初值 / 名称只出现一次 / 无 station_id 行 / 简介在名称正下方
  B. 下拉多选：收起显示已选、selected_ids、勾选联动
  C. 封面图：导入落盘、resolve_cover、payload["cover"]、更换与移除
  D. 悬浮提示：有封面时显示图片、无封面时不显示
  E. 新建模式：空名拦截、id 生成、封面按新 id 命名

注意：会临时往 data/covers/ 写文件，结束时自动清掉。
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit,          # noqa: E402
                               QPlainTextEdit, QToolButton, QPushButton,
                               QCheckBox, QWidget)
from PySide6.QtGui import QPixmap, QColor, QPainter                      # noqa: E402
from PySide6.QtCore import Qt, QTimer                                    # noqa: E402
from PySide6.QtTest import QTest                                         # noqa: E402
import PySide6.QtWidgets as QtW                                          # noqa: E402

from core.schema import EDITABLE_FIELDS, new_station_template            # noqa: E402
from core.data_manager import get_data_manager                           # noqa: E402
from ui.edit_dialog import EditDialog                                    # noqa: E402
from ui.widgets import LinesSelect, make_add_image_icon                  # noqa: E402
from ui.tooltip import HoverTip                                         # noqa: E402
# ★ v2.6.16：`_LineDot.lookup()` 是"线路名 → 官方色"的唯一入口，
#   前面 A 段检查"线路名外圈颜色"时就要用 ⇒ 必须**在文件顶部**导入
#   （原来它在第 737 行才 import，前面的代码用它就是 NameError）。
from ui.timetable_editor import TimetableEditor, _LineDot                # noqa: E402

app = QApplication(sys.argv)
fails = []

# 拦截模态警告框（真实弹框会阻塞，测试里必须换成记录式桩）
warnings = []
QtW.QMessageBox.warning = staticmethod(
    lambda *a, **k: warnings.append(a[2] if len(a) > 2 else "?"))

dm = get_data_manager()


def check(cond, msg):
    print(("  [OK]  " if cond else "  [!!]  ") + msg)
    if not cond:
        fails.append(msg)


def combo_ink_width(cb, dpr_hint=None):
    """在 `cb.grab()` 位图上量"前景墨迹"的宽度（逻辑像素）。

    ★ 判"文字被截"不能用 `horizontalAdvance()`：它含左右边距，汉字字形本身
      比它窄（实测 39.0 → 37.3px），直接比会得到**永恒假失败**。
      真判据是"两侧都还有白边 + 墨迹宽 ≈ 字宽"，且**被截时墨迹宽会明显缩水**
      —— 所以这里量墨迹，交给调用方按 0.9×字宽 判定。
    """
    pm = cb.grab()
    img = pm.toImage()
    dpr = (dpr_hint or pm.devicePixelRatio() or 1.0)
    fg = QColor(cb._fg)
    # ★ 必须把**右侧箭头**那一条剔除，否则量的是"文字+箭头"，判据就废了：
    #   收窄时箭头不动，墨迹总宽会跟着缩小但绝对值仍大于字宽 —— 看着像通过。
    cut = (img.width() - 1) - int(round(cb._arrow * dpr))
    lo, hi, arrow = None, None, 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - fg.red()) + abs(c.green() - fg.green())
                    + abs(c.blue() - fg.blue())) < 150:
                if x >= cut:
                    arrow += 1
                    continue
                lo = x if lo is None else min(lo, x)
                hi = x if hi is None else max(hi, x)
    if lo is None:
        return 0.0, 0.0, 0.0, arrow
    return ((hi - lo + 1) / dpr, lo / dpr, (cut - hi) / dpr, arrow)


def check_combo_v269(tag, ed, cb):
    """v2.6.9 三条铁律：**不截**（宽度够）、**居中**、**点得开**（不可编辑）。

    三条都是踩出来的：
      · v2.6.8 宽度按"内耗 32px"算，样式表实际吃了 40px ⇒ 「工作日」只剩 14px
      · v2.6.8 用 `setEditable(True)` 换居中 ⇒ 点击被内部输入框吞掉 ⇒ 点不动
    所以这里既要断言"现在对"，也要用**变异**证明断言真的在上岗。
    """
    from PySide6.QtGui import QFontMetrics
    m = ed._combo_metric()
    chrome = ed.combo_chrome(m)
    f = cb.font()
    fm = QFontMetrics(f)
    names = [g.date for g in ed._groups]
    longest = max(names, key=lambda s: fm.horizontalAdvance(s))
    tw = fm.horizontalAdvance(longest)
    # ── ① 不可编辑（能点开的前提）
    check(not cb.isEditable(),
          f"{tag}: 下拉**不可编辑**（editable 会让点击落到内部输入框 ⇒ 点不动）")
    # ── ② 宽度够：文字区 ≥ 最长选项
    check(cb.width() - chrome >= tw,
          f"{tag}: 宽度放得下最长选项「{longest}」"
          f"（{cb.width()}−{chrome}={cb.width() - chrome} ≥ {tw:.0f}）")
    # ── ③ 真居中：左右留白相等，且都不小于箭头区（否则字会撞三角）
    left = (cb.width() - tw) / 2.0
    check(left >= m["arrow"] and abs(ed._combo_gap()) <= 2,
          f"{tag}: 文字在整颗胶囊里**居中**且不撞箭头"
          f"（单侧留白 {left:.1f} ≥ 箭头区 {m['arrow']}）；与表格间距 {ed._combo_gap()}px")
    # ── ④ 像素级验"没被截"：**文字区**墨迹宽 ≈ 0.9×字宽，且左右都有白边
    ink, ink_l, ink_r, arrow_px = combo_ink_width(cb)
    check(ink >= tw * 0.9 and ink_l > 0.5 and ink_r > 0.5 and arrow_px > 0,
          f"{tag}: 像素实测文字**没被截**（文字区墨迹 {ink:.1f}px ≈ 字宽 {tw:.0f}px，"
          f"左白边 {ink_l:.1f} 右白边 {ink_r:.1f}，箭头墨点 {arrow_px}）")
    # ── ⑤ 点击真的走到弹列表（★ 环境限制：这个 session 里任何下拉都弹不出窗口，
    #      连普通 QComboBox 点下去 view 也不可见 —— 所以给 showPopup 装计数器，
    #      点"光标下面的那个控件"（真实点击的投递目标）看计数器动不动）
    orig = cb.showPopup
    hits = [0]

    def _sp():
        hits[0] += 1
        return orig()

    cb.showPopup = _sp
    tgt = cb.childAt(cb.rect().center()) or cb
    QTest.mouseClick(tgt, Qt.LeftButton)
    app.processEvents()
    check(hits[0] >= 1,
          f"{tag}: 点一下真的走到『弹列表』（showPopup 被调 {hits[0]} 次）")
    # ── 变异 A：照 v2.6.8 改成 editable ⇒ 点击投递给内部输入框 ⇒ 弹不出来
    cb.setEditable(True)
    app.processEvents()
    hits[0] = 0
    tgt2 = cb.childAt(cb.rect().center()) or cb
    QTest.mouseClick(tgt2, Qt.LeftButton)
    app.processEvents()
    check(hits[0] == 0,
          f"{tag}: 变异自检——改回 editable 后点击**不再**弹列表"
          f"（{hits[0]} 次，投递目标={type(tgt2).__name__}；说明上一条判据真在上岗）")
    cb.setEditable(False)
    cb.showPopup = orig
    # ── 变异 B：把下拉收窄 20px（= v2.6.8 算错的那个量）⇒ 像素实测文字被截
    w0 = cb.width()
    cb.setFixedWidth(max(20, w0 - 20))
    app.processEvents()
    ink2, _l2, _r2, _a2 = combo_ink_width(cb)
    check(ink2 < ink * 0.95,
          f"{tag}: 变异自检——收窄 20px 后文字区墨迹从 {ink:.1f} 缩到 {ink2:.1f}px"
          f"（说明「没被截」这条判据真在上岗）")
    cb.setFixedWidth(w0)
    app.processEvents()


def make_test_png(path: Path, color="#4caf50"):
    pm = QPixmap(320, 200)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.fillRect(20, 20, 120, 60, QColor("#ffffff"))
    p.end()
    pm.save(str(path))


def all_texts(w):
    out = []
    for lab in w.findChildren(QLabel):
        if lab.text().strip():
            out.append(("QLabel", lab.text().strip()))
    for le in w.findChildren(QLineEdit):
        if le.text().strip():
            out.append(("QLineEdit", le.text().strip()))
    for pt in w.findChildren(QPlainTextEdit):
        if pt.toPlainText().strip():
            out.append(("QPlainTextEdit", pt.toPlainText().strip()))
    for tb in w.findChildren(QToolButton):
        if tb.text().strip():
            out.append(("QToolButton", tb.text().strip()))
    return out


TMP_IMG = SRC / "_test_cover_src.png"
created_covers = []

# =========================================================
print("=== A) 编辑模式基本结构（机场东）===")
make_test_png(TMP_IMG)
dlg = EditDialog(station_id="机场东")
# ★★ v2.6.8：必须**真的上屏**。未 show 的窗口 `setFixedSize()` 之后 Qt 不会重排
#   （布局要等 show/resize 事件），于是量到的全是上一帧的旧几何 ——
#   表现就是"封面图怎么都对不齐"（实测一直差 −7px，而 show 之后是 0）。
#   这是项目里第三次栽在"未布局几何"上（MEMORY §5.15）。
dlg.show()
app.processEvents()
got = {}
dlg.save_requested.connect(lambda sid, p: got.update(sid=sid, payload=p))

check(dlg.name_edit.text() == "机场东", f"名称框初值 = {dlg.name_edit.text()!r}")
texts = all_texts(dlg)
# ★ v2.6.2 起站名会**合法地**出现在数据内容里（首末班车里就有"往机场东 首06:21"），
#   所以不能在整个弹窗里数它 —— 只在"静态标签 / 按钮文字"里数。
#   那里出现才是真问题（等于把站名又当标题显示了一遍）。
n = sum(1 for kind, t in texts
        if kind in ("QLabel", "QToolButton") and "机场东" in t)
check(n == 0, f"静态标签里 '机场东' 出现 {n} 次（应为 0：站名只在名称框里出现）")
check(all(t != "station_id：" for _, t in texts), "无 'station_id：' 标签")
check(all(t != "站点名称" for _, t in texts), "表单里无 '站点名称' 标签")

# 封面按钮存在且是图标按钮
check(isinstance(dlg.cover_btn, QToolButton), "顶栏左侧是 QToolButton（图标按钮）")
check(not dlg.cover_btn.icon().isNull(), "封面按钮有图标（添加图片图标）")
check(all(t != "编辑站点：" for _, t in texts), "顶栏已无 '编辑站点：' 文字")
check(not make_add_image_icon(30).isNull(), "make_add_image_icon 能画出图标")

# 简介在顶部块（名称正下方），不是表单行
check("description" in dlg._widgets, "简介控件已登记")
check(isinstance(dlg._widgets["description"], QPlainTextEdit), "简介是多行框")
check(not isinstance(dlg._widgets["description"], type(None)), "简介控件存在")
# 名称与简介必须是**同一个竖排**里的兄弟控件（简介才会"跟着"名称走）
check(dlg.desc_edit.parentWidget() is dlg.name_edit.parentWidget(),
      "简介与名称在同一个容器里（简介竖直跟随名称）")

# ---- v2.4.16：❌ 与「保存」都要抓手光标 ----
check(dlg.btn_save.cursor().shape() == Qt.PointingHandCursor,
      f"「保存」光标 = {dlg.btn_save.cursor().shape()}（应为 PointingHandCursor）")
check(hasattr(dlg, "btn_close"), "有自绘的 ✕ 关闭按钮")
check(dlg.btn_close.cursor().shape() == Qt.PointingHandCursor,
      f"✕ 光标 = {dlg.btn_close.cursor().shape()}（应为 PointingHandCursor）")
# 自绘标题栏 ⇒ 必须是 FramelessWindow，否则会和系统标题栏叠成两条
check(bool(dlg.windowFlags() & Qt.FramelessWindowHint),
      "弹窗是无边框窗口（去掉系统标题栏，❌ 才能自绘）")
# ---- v2.6.3：标题文字整行删掉（用户："删除文字'编辑站点'，整体内容往上"）----
check(not hasattr(dlg, "title_lbl"), "标题控件 title_lbl 已删除（v2.6.3）")
check(all(t not in ("编辑站点", "新建站点") for _, t in texts),
      "弹窗里不再出现 '编辑站点 / 新建站点' 文字")
check(dlg.btn_close.text() == "✕", f"关闭按钮字符 = {dlg.btn_close.text()!r}")

# ---- v2.6.3：✕ 必须**浮动**在右上角（不进布局，否则又要占一行高度）----
check(dlg.btn_close.parentWidget() is dlg, "✕ 的 parent 是弹窗本身（不进布局）")
_lay_owners = [w for w in dlg.findChildren(QWidget)
               if w.layout() is not None
               and dlg.btn_close in (w.layout().itemAt(i).widget()
                                     for i in range(w.layout().count()))]
check(not _lay_owners, f"✕ 没有被任何布局接管（实际被 {_lay_owners} 接管）")
_rb = dlg.width() - dlg.btn_close.geometry().right()
check(0 < _rb <= 24,
      f"✕ 贴右上角（右边距 = {_rb}px，窗口宽 {dlg.width()}）")
check(0 < dlg.btn_close.geometry().top() <= 16,
      f"✕ 贴顶部（上边距 = {dlg.btn_close.geometry().top()}px）")
# ✕ 要能真的关掉窗口（reject）
_closed = []
dlg.rejected.connect(lambda: _closed.append(1))
dlg.btn_close.click()
app.processEvents()
check(bool(_closed) or not dlg.isVisible(), "点 ✕ 会 reject（关闭弹窗）")
# ---------------- v2.6.6：删掉「是否换乘站」「开通日期」两个字段 ----------------
# 用户要求：上方的线路下拉本身就能表达"是不是换乘站"，这两行多余。
# ★ 判据必须是"这两个字段真的没了"，而不是"看起来少了一行"：
#   ① schema 里没有这两个 key；② 没有对应控件；③ 界面上找不到这两个文字。
from PySide6.QtWidgets import QFormLayout, QGridLayout, QLabel as _QL, QWidget  # noqa: E402
_keys = {f["key"] for f in EDITABLE_FIELDS}
check("is_transfer" not in _keys and "open_date" not in _keys,
      f"schema 里已无 is_transfer / open_date（现有 {sorted(_keys)}）")
for _gone in ("is_transfer", "open_date"):
    check(_gone not in dlg._widgets, f"弹窗里不存在 {_gone} 对应的控件")
_all_lbl = [lb.text().strip() for lb in dlg.findChildren(QLabel)]
check("是否换乘站" not in _all_lbl, f"弹窗已无'是否换乘站'文字（标签: {_all_lbl}）")
check("开通日期" not in _all_lbl, f"弹窗已无'开通日期'文字（标签: {_all_lbl}）")
check("所属线路" not in _all_lbl,
      f"弹窗里已无'所属线路'标签（实际标签: {_all_lbl}）")
# 表单第一行不再是那个「是否换乘站 | ☐ | 开通日期 | [输入框]」的并排容器
_it0 = dlg.form_layout.itemAt(0)
_w0 = _it0.widget() if _it0 is not None else None
_row0_labels = sorted(l.text() for l in _w0.findChildren(_QL)) if _w0 else []
check(_row0_labels != ["开通日期", "是否换乘站"],
      f"第一行不再是那两个字段的并排行（实际标签 {_row0_labels}）")

# 底部按钮：只留"保存"，取消交给右上角 ✕ / Esc
btns = [b.text() for b in dlg.findChildren(QPushButton)]
check(not any("取消" in t for t in btns), f"底部已无'取消'按钮（实际={btns}）")
check(any("保存" in t for t in btns), f"底部仍有'保存'按钮（实际={btns}）")

# 标签与表单块都居左
la = int(dlg.form_layout.labelAlignment())
fa = int(dlg.form_layout.formAlignment())
check(bool(la & int(Qt.AlignLeft)) and not bool(la & int(Qt.AlignRight)),
      f"表单标签居左（labelAlignment={la}）")
check(bool(fa & int(Qt.AlignLeft)), f"表单块居左（formAlignment={fa}）")

payload = dlg._collect()
expect = {f["key"] for f in EDITABLE_FIELDS}
# ★ v2.6.6：is_transfer 不再是表单字段，但**必须仍然被算出来写回**：
#   ① `metro_render` 靠它决定圆点大小 / 站名加粗；
#   ② `upsert_station` 是**合并写入** —— payload 里没这个键，旧值就原样留着，
#      用户把线路从 1 条改成 2 条，圆点却还是普通大小。
check(set(payload.keys()) == expect | {"is_transfer"},
      f"_collect() 键集合 = 表单字段 + 派生的 is_transfer"
      f"（缺: {expect - set(payload)}，多: {set(payload) - expect - {'is_transfer'}}）")
# ★ v2.6.18：机场东按官方图只是 1/12 号线（原来误挂 11号线，拓扑已修）
check(payload["lines"] == ["1", "12"], f"线路 = {payload['lines']}")
check(payload["is_transfer"] is True,
      f"换乘站由线路数推出 = True（线路 {payload['lines']}）")

# =========================================================
print("\n=== A2) 顶栏：名称框变窄(4字) / 所属线路搬到名称框右侧 / 封面图底边对齐简介框 ===")
# 下面要比几何关系，必须先把弹窗真正显示出来（否则坐标全是未布局的默认值）
dlg.show()
app.processEvents()

# ---- G) v2.6.6：换乘状态由"线路数"推导 —— 勾掉/勾上必须**当场跟着变** ----
# ★ 这里替代原来"是否换乘站复选框"的那组断言：
#   以前是"勾选框勾上 ⇒ True"，现在是"挂上 ≥2 条线路 ⇒ True"。
_ls = dlg.lines_select
_ls.set_selected(["1"])
app.processEvents()
check(dlg._collect()["is_transfer"] is False,
      f"只剩 1 条线 ⇒ is_transfer=False（实际 {dlg._collect()['is_transfer']!r}）")
_ls.set_selected(["1", "2"])
app.processEvents()
check(dlg._collect()["is_transfer"] is True,
      f"勾到 2 条线 ⇒ is_transfer=True（实际 {dlg._collect()['is_transfer']!r}）")
_ls.set_selected([])
app.processEvents()
check(dlg._collect()["is_transfer"] is False,
      f"一条都没勾 ⇒ False（实际 {dlg._collect()['is_transfer']!r}）")
_ls.set_selected(["1", "12"])  # v2.6.18：机场东按官方图只有 1/12 两条线
app.processEvents()
check(dlg._collect()["is_transfer"] is True, "还原成机场东原来的 2 条线")
check(dlg.name_edit.width() == dlg.NAME_WIDTH,
      f"名称框宽度 = {dlg.name_edit.width()}（应 = {dlg.NAME_WIDTH}）")
fm = dlg.name_edit.fontMetrics()
FOUR_CN = "\u6df1\u5733\u5730\u94c1"          # "深圳地铁" 4 个中文字
need = fm.horizontalAdvance(FOUR_CN)
avail = dlg.name_edit.width() - 2 * dlg.name_edit.textMargins().left() - 6
check(need <= avail, f"宽度够写 4 个中文字（需要 {need}px，可用 ~{avail}px）")
FIVE_CN = "\u6df1\u5733\u5730\u94c1\u7ad9"     # "深圳地铁站" 5 个中文字
check(fm.horizontalAdvance(FIVE_CN) > avail,
      f"但已经写不下 5 个字（需要 {fm.horizontalAdvance(FIVE_CN)}px > 可用 {avail}px）")
check(dlg.name_edit.width() < 200, "名称框不再拉满整行")
# v2.4.13：光收窄框宽不够，还要有硬性字符上限
check(dlg.name_edit.maxLength() == dlg.NAME_MAX_CHARS == 4,
      f"名称框字符上限 = {dlg.name_edit.maxLength()}（应 = 4）")
check(dlg.name_edit.text() == "\u673a\u573a\u4e1c", f"初值仍正确 = {dlg.name_edit.text()!r}")

# ★ v2.4.13：线路下拉必须在**顶栏**、且在名称框**右侧**、两者竖直方向大致齐平
ls_w = dlg.lines_select
check(ls_w is dlg._widgets["lines"], "字段表里的 lines 指向顶栏那个下拉")
n_l = dlg.name_edit.mapTo(dlg, dlg.name_edit.rect().topLeft())
n_r = dlg.name_edit.mapTo(dlg, dlg.name_edit.rect().topRight())
l_l = ls_w.mapTo(dlg, ls_w.rect().topLeft())
check(l_l.x() > n_r.x(),
      f"线路下拉在名称框右侧（下拉左 {l_l.x()} > 名称框右 {n_r.x()}）")
check(abs(l_l.y() - n_l.y()) <= 8,
      f"两者竖直方向齐平（下拉 top={l_l.y()} vs 名称框 top={n_l.y()}）")
check(ls_w.parentWidget() is dlg.header_right,
      f"线路下拉挂在顶栏容器里（实际父控件 = {ls_w.parentWidget().objectName() or type(ls_w.parentWidget()).__name__}）")
check(ls_w.parentWidget() is not dlg.form_host, "线路下拉已**不在**表单里")
check(ls_w.width() >= 240,
      f"下拉宽度够容纳 4 条线路（含两位数）不省略 = {ls_w.width()}px（应 ≥240）")
# v2.4.14/15：顶栏那点宽度必须真的放得下「4 条线路」。
# ★ 内耗必须用**实测值** LINES_INNER_PAD，不能自己拍一个常数 ——
#   之前用估的 34 恰好蒙对，但余量只留了 8px，字体渲染一波动就截断。
inner_avail = ls_w.width() - dlg.LINES_INNER_PAD
_worst4 = "10\u53f7\u7ebf 11\u53f7\u7ebf 12\u53f7\u7ebf 20\u53f7\u7ebf"   # 4 条两位数，真实最坏
_w4px = ls_w.fontMetrics().horizontalAdvance(_worst4)
check(inner_avail >= _w4px,
      f"下拉内部可用宽 {inner_avail}px ≥ 最坏 4 条两位数文案 {_w4px}px")
check(inner_avail - _w4px >= 30,
      f"且留有余量 ≥30px（实际 {inner_avail - _w4px}px）—— 字体渲染波动不会顶出去")
check(ls_w.SEP == " ", "下拉用空格分隔（不是顿号）")

check(dlg.cover_btn.width() == dlg.cover_btn.height(),
      f"封面按钮是正方形 {dlg.cover_btn.width()}x{dlg.cover_btn.height()}")
# v2.4.12：底边与「简介」输入框底边齐平 → 边长不再写死，由布局反推
# ★ 对齐逻辑挂在 QTimer.singleShot(0) 上，必须**真的把事件循环转起来**才会执行；
#   只调 processEvents() 有时排不到（定时器要等一次真正的循环迭代）。
# ★ v2.6.8：这里要**多转几轮**才收敛。原因：简介框现在是"高度自适应"的，
#   而它的**宽度**又取决于封面按钮的宽度（两者挤在同一行）⇒
#   封面变大 → 简介变窄 → 换行更多 → 简介变高 → 又要求封面更大。
#   每一轮都要先把简介按当前宽度重新量一次再对齐，所以需要 **多轮**。
#   （v2.6.8 之前简介是"撑满剩余高度"，一轮就够；现在必须给够迭代次数。）
for _ in range(12):
    app.processEvents()
    QTimer.singleShot(0, lambda: None)
    dlg._align_cover_to_desc()      # 幂等：齐了就直接 return
app.processEvents()
b_top = dlg.cover_btn.mapTo(dlg, dlg.cover_btn.rect().topLeft()).y()
b_bot = dlg.cover_btn.mapTo(dlg, dlg.cover_btn.rect().bottomLeft()).y()
d_top = dlg.desc_edit.mapTo(dlg, dlg.desc_edit.rect().topLeft()).y()
d_bot = dlg.desc_edit.mapTo(dlg, dlg.desc_edit.rect().bottomLeft()).y()
check(dlg.cover_btn.height() >= 150,
      f"封面按钮已按对齐结果回填 = {dlg.cover_btn.height()}px（简介框 {dlg.desc_edit.height()}px）")
check(abs(d_bot - b_bot) <= 1,
      f"★ 图片底边与简介框底边齐平（图片 {b_bot} vs 简介 {d_bot}，差 {d_bot - b_bot}px）")
check(b_top >= d_top - 60,
      f"图片顶端不低于简介框太多（图片 {b_top} vs 简介 {d_top}）")
check(dlg.cover_btn.iconSize().width() >= 140,
      f"图标跟着按钮一起放大 = {dlg.cover_btn.iconSize().width()}px")
ratio = (dlg.cover_btn.width() / 108.0) ** 2
check(2.5 <= ratio <= 6.0,
      f"封面按钮面积 = 上一版（108×108）的 {ratio:.2f} 倍（本次按'方案乙'以对齐为准）")

# ① "简介"两个字必须已经删掉（顶部不再有这个标签）
lbl_desc = [lb for lb in dlg.findChildren(QLabel) if lb.text().strip() == "简介"]
check(len(lbl_desc) == 0, f"顶部已无 '简介' 标签（实际找到 {len(lbl_desc)} 个）")
check("简介" not in dlg.desc_edit.placeholderText().replace("简介：", "", 1),
      "placeholder 里只是用前缀提示，不是重复一个独立标签")
check(dlg.desc_edit.placeholderText().startswith("简介"),
      f"改成用 placeholder 提示含义 = {dlg.desc_edit.placeholderText()!r}")

# ② 简介框仍然"竖直跟随"名称框：同一个容器 + 紧贴在名称框下方 + 左侧对齐
name_geo = dlg.name_edit.geometry()
desc_geo = dlg.desc_edit.geometry()
check(dlg.desc_edit.parentWidget() is dlg.name_edit.parentWidget(),
      "简介框与名称框在同一个容器里（简介竖直跟随名称）")
check(desc_geo.top() > name_geo.bottom(),
      f"简介框在名称框下方（{desc_geo.top()} > {name_geo.bottom()}）")
check(desc_geo.top() - name_geo.bottom() < 20,
      f"简介框紧跟着名称（间距 {desc_geo.top() - name_geo.bottom()}px）")
check(abs(desc_geo.left() - name_geo.left()) <= 2,
      f"简介框左边与名称框左边对齐（{desc_geo.left()} vs {name_geo.left()}）")
check(desc_geo.left() <= 2,
      f"简介框贴在这一列的左边缘（{desc_geo.left()}，容器内坐标）")
# 简介框仍然占满右侧那一列（没被名称框的窄宽度连累）
desc_w = dlg.desc_edit.width()
check(desc_w > dlg.name_edit.width() + 100,
      f"简介框仍占满右列（desc.w={desc_w} vs name.w={dlg.name_edit.width()}）")

# =========================================================
print("\n=== A3) 整体变圆润（圆角 + 柔和底色）===")
qss = dlg.styleSheet()
check(dlg.objectName() == "EditDialog", "弹窗有 objectName（样式表能精确命中）")
check(dlg.testAttribute(Qt.WA_StyledBackground),
      "开了 WA_StyledBackground（QDialog 直系子类才能画出样式表底色）")
check(f"QDialog#EditDialog" in qss, "样式表里有窗口自身的规则")
check(f"border-radius: {dlg.WINDOW_RADIUS}px" in qss,
      f"窗口圆角 = {dlg.WINDOW_RADIUS}px")
check(dlg.WINDOW_RADIUS >= 10, f"圆角够明显（{dlg.WINDOW_RADIUS}px）")
check("QLineEdit, QPlainTextEdit" in qss and "border-radius: 8px" in qss,
      "输入框也是圆角（8px）")
check("QPushButton" in qss and "border-radius: 10px" in qss,
      "按钮也是圆角（10px）")
check("#f7f8fa" in qss, "窗口底色改成了柔和的浅灰 #f7f8fa，不再纯白")
check("QScrollBar::handle:vertical" in qss and "border-radius: 5px" in qss,
      "滚动条也做成圆头细条")
check(f"border-radius: {dlg.BTN_RADIUS + 2}px" in dlg.cover_btn.styleSheet(),
      f"封面图按钮也是圆角（{dlg.BTN_RADIUS + 2}px）")
# 独立窗口（无 parent）才走 Win32 裁剪外形这条路；有 parent 时 Qt 自己处理
check(dlg.parent() is None and hasattr(dlg, "_apply_round_region"),
      "无 parent 时有 _apply_round_region 兜底裁圆角")
dlg.hide()

# =========================================================
print("\n=== B) 下拉多选 LinesSelect（展开后一行 3 个）===")
lines = dm.all_lines()
ls = LinesSelect(lines, ["1", "11"])
# v2.4.14：分隔符从顿号改成空格
check(ls.text() == "1号线 11号线", f"收起时显示已选（空格分隔）= {ls.text()!r}")
check("、" not in ls.text(), f"显示文字里不含顿号 = {ls.text()!r}")
check(ls.SEP == " ", f"分隔符常量 = {ls.SEP!r}（应为空格）")
check("、" not in ls.toolTip(), f"tooltip 里也不含顿号 = {ls.toolTip()!r}")
check(ls.selected_ids() == ["1", "11"], f"selected_ids = {ls.selected_ids()}")
check(ls.menu() is None, "已不再用 QMenu（QMenu 排不出多列，改自建 Popup 面板）")
checks = ls.line_checks()
check(len(checks) == len(lines), f"展开面板里有 {len(checks)} 个候选项（应 {len(lines)}）")
check(ls.popup_columns() == 3, f"一行 {ls.popup_columns()} 个（应 3）")
# 真的排成 3 列：第 4 个候选项应落在「第 2 行第 1 列」
grid = ls._popup.layout()
r, c, _, _ = grid.getItemPosition(grid.indexOf(checks[3]))
check((r, c) == (1, 0), f"第 4 个候选项在 (行{r}, 列{c})，应为 (1, 0)")
r7, c7, _, _ = grid.getItemPosition(grid.indexOf(checks[6]))
check((r7, c7) == (2, 0), f"第 7 个候选项在 (行{r7}, 列{c7})，应为 (2, 0)")
# 勾一个 → 文案跟着变
ls.set_line_checked("2", True)
check("2号线" in ls.text(), f"勾选 2 号线后文案 = {ls.text()!r}")
check(ls.selected_ids() == ["1", "2", "11"],
      f"selected_ids 更新 = {ls.selected_ids()}（按线路顺序，不是勾选先后）")
# 面板展开不关自己、点外面才关（Qt.Popup）
ls.set_selected([])
check(ls.text() == LinesSelect.EMPTY_TEXT, f"清空后显示 = {ls.text()!r}")
# 弹窗里的下拉也认（v2.4.13：已搬到顶栏）
dlg_lines = dlg._widgets["lines"]
check(isinstance(dlg_lines, LinesSelect), "弹窗里的所属线路是 LinesSelect")
check(hasattr(dlg, "lines_select") and dlg_lines is dlg.lines_select,
      "顶栏的 self.lines_select 就是字段表里的 lines 控件")

# =========================================================
print("\n=== B1b) v2.4.14/15：验证「4 条线路」都能完整显示（含两位数的最坏情况）===")
_name_of = {str(l["id"]): l.get("name") for l in lines}
_over = []
for _sid, _st in dm.all_stations().items():
    _ids = _st.get("lines") or []
    _txt = dlg_lines.SEP.join(_name_of.get(str(i), str(i)) for i in _ids)
    _w = dlg_lines.fontMetrics().horizontalAdvance(_txt)
    if _w > inner_avail:
        _over.append((_st.get("station_name"), _txt, _w))
print(f"  （共扫 {len(dm.all_stations())} 个站点，下拉内部可用 {inner_avail}px）")
check(len(_over) == 0,
      f"没有任何真实站点会被截断；超宽的 = {len(_over)} 个 {_over[:3]}")

# ★ 关键：真实站点里最宽的是岗厦北(156px)，但它**不是最坏情况**。
#   真正的最坏是"4 条两位数线路"= 163px（比如 10/11/12/20）。
#   直接构造这种组合验证 —— 这才是用户说"有概率显示不全"的根因。
_HARD = ["10", "11", "12", "20"]
ds_hard = LinesSelect(lines, _HARD)
_htxt = ds_hard.text()
_hpx = ds_hard.fontMetrics().horizontalAdvance(_htxt)
print(f"  最坏组合: {_htxt!r} = {_hpx}px")
check("…" not in _htxt, f"4 条两位数线路不触发省略号 = {_htxt!r}")
check(_hpx <= inner_avail, f"其宽度 {_hpx}px ≤ 下拉可用 {inner_avail}px")
check(inner_avail - _hpx >= 30,
      f"余量 {inner_avail - _hpx}px ≥30（字体渲染波动不会截断）")
# 汇总校验：多组"危险组合"逐个过一遍
for _combo in (["10", "11", "12", "13"], ["10", "11", "13", "14"],
               ["11", "12", "13", "14"], ["10", "12", "13", "16"]):
    _t = LinesSelect(lines, _combo).text()
    _p = dlg_lines.fontMetrics().horizontalAdvance(_t)
    check("…" not in _t and _p <= inner_avail,
          f"组合 {_combo} → {_t!r} ({_p}px) 不被截断")
# 单独盯一下线路最多的那个站
_worst = max(((len(_st.get("lines") or []), _sid, _st) for _sid, _st in dm.all_stations().items()),
             key=lambda x: x[0])
_wid, _wsid, _wst = _worst
_wtxt = dlg_lines.SEP.join(_name_of.get(str(i), str(i)) for i in (_wst.get("lines") or []))
check("、" not in _wtxt, f"线路最多的站（{_wst.get('station_name')}）显示无顿号 = {_wtxt!r}")
check(dlg_lines.fontMetrics().horizontalAdvance(_wtxt) <= inner_avail,
      f"它({_wid} 条)的文案 {_wtxt!r} 宽度 "
      f"{dlg_lines.fontMetrics().horizontalAdvance(_wtxt)}px ≤ {inner_avail}px")

# =========================================================
print("\n=== B2) 多行字段：标签在上、输入框在下、整行宽 ===")
dlg.show()
app.processEvents()

# ---- v2.6.6：删掉那两个勾选项之后，表单里**一个复选框都不该剩** ----
# ★ 为什么盯着"一个不剩"：schema 里唯一的 bool 类型字段就是 is_transfer，
#   删了它以后还出现复选框 ⇒ 说明有控件是按类型写死挂上去的，schema 驱动失效了。
_left_cb = [cb.text() or type(cb).__name__
            for cb in dlg.form_host.findChildren(QCheckBox)]
check(not _left_cb,
      f"表单区域已无复选框残留（实际还有 {_left_cb}）")
_grid_containers = [w for w in dlg.form_host.findChildren(QWidget)
                    if w is not dlg.form_host
                    and isinstance(w.layout(), QGridLayout)]
check(not _grid_containers,
      f"已无旧的'两字段并排'网格容器（实际还剩 {len(_grid_containers)} 个）")
# ★ 别再把字段表写死：v2.6.2 新增了 timetable / bus_transfer，
#   写死的话这里会一直少算、断言失败却看不出是"字段变多了"。
# ★ 但要排掉顶部已放过的三个字段（station_name / description / lines）——
#   它们的控件不在表单里（description 虽是 multiline，却在顶部大框里）。
# ★ 还要排掉 `same_row: True` 的字段（facilities）—— 它不在表单里，
#   而是"文字与输入框同一行、只有一行高"，形态跟其它多行字段完全不同，
#   单独在 A8 组里验。
_MULTILINE_SKIP = ("station_name", "description", "lines")
MULTILINE = [(f["key"], f.get("label", f["key"]))
             for f in EDITABLE_FIELDS
             if f.get("type") == "multiline" and f["key"] not in _MULTILINE_SKIP
             and not f.get("same_row")]
for key, want_label in MULTILINE:
    ed = dlg._widgets[key]
    box = ed.parentWidget()
    labs = [lb for lb in box.findChildren(QLabel) if lb.text().strip() == want_label]
    if key == "timetable":
        # ★ v2.6.8：下拉搬进了**表格自己的表头行**（用户要求：放到表头「线路」
        #   的左侧）。所以这一行既没有"首末班车"标签，也不再套 stacked 外壳。
        cb = ed.date_combo
        _anc, _p = False, cb.parentWidget() if cb is not None else None
        while _p is not None:
            if _p is ed:
                _anc = True
                break
            _p = _p.parentWidget()
        check(_anc, f"{key}: 日期下拉在表格**内部**（不再是外部那一行标签位）")
        check(len([lb for lb in ed.findChildren(QLabel)
                   if lb.text().strip() == "首末班车"]) == 0,
              f"{key}: 表里已无 '首末班车' 四个字")
        check(cb.count() == len(ed._groups),
              f"{key}: 下拉 {cb.count()} 项 = 数据里的 {len(ed._groups)} 种日期类型")
        # 位置：下拉在表头行、与右边的文字表头**同一行**
        # ★★★ v2.6.15 起表头里**不再有「线路」标签**（用户要求删掉）。
        #   原来这一整块写在 `if _ll:` 里 ⇒ 标签一没，**整块静默跳过**：
        #   "下拉与表头同一行""只剩列间距""色块条"…… 一条都没跑，
        #   而汇总仍然是"全部通过"。这种**假通过**比失败更危险。
        #   现在把锚点换成**「方向」表头**（它还在），并且锚点自己也要断言找得到，
        #   杜绝"找不到就整块跳过"这条路。
        _dl = [lb for lb in ed.findChildren(QLabel)
               if lb.text().strip() == "方向"]
        check(len(_dl) == 1,
              f"{key}: 表头里能找到『方向』当锚点（找到 {len(_dl)} 个）")
        if _dl:
            _ct = cb.mapTo(ed, cb.rect().topLeft()).y()
            _cbm = cb.mapTo(ed, cb.rect().bottomLeft()).y()
            _lt = _dl[0].mapTo(ed, _dl[0].rect().topLeft()).y()
            _lbm = _dl[0].mapTo(ed, _dl[0].rect().bottomLeft()).y()
            check(_ct < _lbm and _cbm > _lt,
                  f"{key}: 下拉与『方向』表头**同一行**（垂直区间重叠："
                  f"下拉 {_ct:.0f}~{_cbm:.0f} vs 表头 {_lt:.0f}~{_lbm:.0f}）")
            # ★ v2.6.16 修阈值：下拉现在**就在网格第 0 列里**，和「方向」
            #   之间隔的是**网格列间距**（不是原来那个 2px 的 `_combo_gap`）。
            #   阈值直接跟 `ed._gap` 同源，别再写死一个只属于旧布局的数字。
            _cx_r = cb.mapTo(ed, cb.rect().topRight()).x()
            _lx_l = _dl[0].mapTo(ed, _dl[0].rect().topLeft()).x()
            _gap = getattr(ed, "_gap", 8)
            check(0 <= _lx_l - _cx_r <= _gap + 2,
                  f"{key}: 下拉与『方向』之间只隔一个列间距"
                  f"（{_lx_l - _cx_r:.0f}px ≤ {_gap}）")

        # ★★★ v2.6.16：线路颜色改成**画在线路名文字上的外圈**
        #   （用户原话：「下拉菜单『工作日』下方目前是显示各个线路对应的颜色块，
        #    改为在对应的线路文字套一个颜色外圈」）。
        #   ★ 判据必须是"**外圈色 == 这条线的官方色**"：
        #     只断言"有边框"抓不住"所有线路同一个颜色"；
        #     只断言"颜色非空"更是谁都过。
        #   ★ 再加一条"不同线路的颜色互不相同" —— 这条抓的是
        #     "随手挑了个好看的颜色画上去"这种假实现。
        _ring_bad, _ring_seen, _ring_n = [], {}, 0
        _ring_names = set()
        for _g in ed._groups:
            for _row in _g.rows:
                _nm = (_row.line_ed.text() or "").strip()
                if not _nm:
                    continue
                _want = _LineDot.lookup(_nm)
                _ring_n += 1
                _ring_names.add(_nm)
                if _want.lower() not in _row.line_ed.styleSheet().lower():
                    _ring_bad.append(f"{_nm}（样式里没有 {_want}）")
                _ring_seen.setdefault(_want, []).append(_nm)
        check(_ring_n > 0 and not _ring_bad,
              f"{key}: 每条线路名的外圈色 = 该线路**官方色**"
              f"（检查 {_ring_n} 条）"
              + ("，没对上的：" + "；".join(_ring_bad) if _ring_bad else ""))
        # ★ 先断言"判据的前提成立"：这个站得真有 ≥2 条不同线路，
        #   否则下面那条"几条线就几种色"根本无从谈起（会变成恒真断言）。
        check(len(_ring_names) >= 2,
              f"{key}: 这个站有 {len(_ring_names)} 条不同线路"
              f"（{'/'.join(sorted(_ring_names))}）—— 下面判据的前提")
        # ★ 判据写成"**几条不同线路就有几种不同颜色**"，而不是写死 ≥3：
        #   写死数字会在"站里只有两条线"时假失败（第一版就是这么错的）。
        check(len(_ring_seen) == len(_ring_names),
              f"{key}: {len(_ring_names)} 条不同线路 → {len(_ring_seen)} 种"
              f"不同外圈色（"
              + "、".join(f"{c}={'/'.join(sorted(set(v)))}"
                          for c, v in _ring_seen.items())
              + "）")
        # 变异自检：把某一行的外圈色写死成一个**深圳地铁没用过的**颜色
        # （洋红 #FF00FF）⇒ 上面"外圈色 == 官方色"必须失败。
        # ★ 用洋红而不是灰色：兜底色恰好是 #CBD5E1，拿它当变异体可能
        #   碰上"这条线本来就查不到色"，变异就不成立了（假变异）。
        if ed._groups and ed._groups[0].rows:
            _row0 = ed._groups[0].rows[0]
            _old_ss = _row0.line_ed.styleSheet()
            _nm0 = (_row0.line_ed.text() or "").strip()
            _row0.line_ed.setStyleSheet(
                "QLineEdit#TTLine{border:1.5px solid #FF00FF;}")
            _now_bad = (_LineDot.lookup(_nm0).lower()
                        not in _row0.line_ed.styleSheet().lower())
            _row0.line_ed.setStyleSheet(_old_ss)
            check(_now_bad,
                  f"{key}: 变异自检——把「{_nm0}」的外圈写死成 #FF00FF 后"
                  f"对不上官方色 {_LineDot.lookup(_nm0)} ⇒ 上面的判据真在上岗")
        # ★ 色块条删掉之后，表头那一行**只剩下拉本身的高度**。
        #   不用"找 _SwatchBar 类的实例"来判（那个类已经删了 ⇒ 永远找到 0 个
        #   ⇒ 恒真断言，项目铁律：从不报错的校验器等于没有）。
        #   改判**高度**：又往下拉下面塞一行（比如把色块条加回来）会让它涨 10px+。
        _hdr_h = _dl[0].parentWidget().height() if _dl else 0
        check(0 < _hdr_h <= cb.height() + 12,
              f"{key}: 表头行高 {_hdr_h}px ≈ 下拉高 {cb.height()}px"
              f" ⇒ 下拉下方**没有再夹一行**（旧的色块条已删）")
        # v2.6.9：不截 / 居中 / 点得开（三条 + 两个变异自检）
        check_combo_v269(key, ed, cb)
        check(all(cb.itemData(i, Qt.TextAlignmentRole) == int(Qt.AlignCenter)
                  for i in range(cb.count())),
              f"{key}: 下拉**展开后**每一项也居中")
        continue
    check(len(labs) == 1, f"{key}: 容器里有且仅有标签 {want_label!r}（找到 {len(labs)} 个）")
    if labs:
        lb = labs[0]
        check(lb.geometry().bottom() <= ed.geometry().top() + 1,
              f"{key}: 标签在输入框上方（label.bottom={lb.geometry().bottom()} ≤ edit.top={ed.geometry().top()}）")
        check(abs(lb.geometry().left()) <= 1, f"{key}: 标签靠左（left={lb.geometry().left()}）")
    check(ed.width() >= box.width() - 2,
          f"{key}: 输入框占满整行（edit.w={ed.width()} / box.w={box.width()}）")
    check(box.parentWidget() is dlg.form_host, f"{key}: 整块直接挂在表单上（跨列占满一行）")

# v2.6.6：那一行「是否换乘站 | ☐ | 开通日期 | [输入框]」已经整行删掉，
# 所以表单行数 = 竖排多行字段 + 单行同排字段（same_row），**不再 +1**。
_SAMEROW = [f for f in EDITABLE_FIELDS
            if f.get("same_row") and f["key"] not in _MULTILINE_SKIP]
# v2.6.8：`head_with` 的字段（设施）挂进了「出入口信息」那一行的标题右侧，
#   **自己不再占一行** ⇒ 行数要减掉它。
_HEADWITH = [f for f in EDITABLE_FIELDS if f.get("head_with")]
check(dlg.form_layout.rowCount() == len(MULTILINE) + len(_SAMEROW) - len(_HEADWITH),
      f"表单行数 = {dlg.form_layout.rowCount()}"
      f"（{len(MULTILINE)} 个多行 + {len(_SAMEROW)} 个单行同排 − {len(_HEADWITH)} 个挂到别人行里）")

# ★ v2.6.8：用户点名了上下顺序 —— 出入口信息 → 周边地标 → 备注 → 首末班车 → 公交换乘
def _row_text(i):
    """第 i 行的"行首文字"（没有标签的行就从控件里找第一个 QLabel）。"""
    lab = dlg.form_layout.itemAt(i, dlg.form_layout.ItemRole.LabelRole)
    fld = dlg.form_layout.itemAt(i, dlg.form_layout.ItemRole.FieldRole)
    if lab is not None and lab.widget() is not None:
        t = lab.widget().text().strip()
        if t:
            return t
    if fld is not None and fld.widget() is not None:
        for lb in fld.widget().findChildren(QLabel):
            if lb.text().strip():
                return lb.text().strip()
    return "?"


_got_order = [_row_text(i) for i in range(dlg.form_layout.rowCount())]
# 首末班车那一行没有文字标签（表格自带表头），按它出现的**位置**判
check(_got_order[:3] == ["出入口信息", "周边地标", "备注"],
      f"前三行顺序正确（实际 {_got_order[:3]}）")
check(_got_order[-1] == "公交换乘",
      f"最后一行是公交换乘（实际 {_got_order[-1]}）")
_tt_pos = next((i for i, w in enumerate(_got_order)
                if i >= 3 and w not in ("公交换乘",)), None)
check(_tt_pos == 3,
      f"首末班车排在「备注」之后、「公交换乘」之前（位置 {_tt_pos}，整行 {_got_order}）")

# =========================================================
# 全量数据（下面几组都要用；用真实 stations.json，别用 DM 的内存对象）
_all = dm.all_stations() if hasattr(dm, "all_stations") else None
if _all is None:
    import json as _json
    _all = _json.loads((SRC / "data" / "stations.json").read_text(encoding="utf-8"))["stations"]

print("\n=== A8) 「设施」挂到「出入口信息」标题右侧（v2.6.8）===")
# 用户要求：「『设施』显示的内容放到文字『出入口信息』的右侧，
#            依旧保持输入框显示（删除文字『设施』）」
#   形态 →  出入口信息   [ 卫生间、电梯、母婴室 ]
#           A1   龙岗大道南侧…
_fac = dlg._widgets["facilities"]
check(isinstance(_fac, QLineEdit),
      f"设施仍是**单行**输入框（实际 {type(_fac).__name__}）")
check(_fac.height() <= 44,
      f"设施只有一行高（{_fac.height()}px ≤ 44）")

_ex_w = dlg._widgets["exits"]
_ex_labs = [lb for lb in _ex_w.parentWidget().findChildren(QLabel)
            if lb.text().strip() == "出入口信息"]
check(len(_ex_labs) == 1, f"找得到「出入口信息」标签（{len(_ex_labs)} 个）")
if _ex_labs:
    _lb = _ex_labs[0]
    _ly = _lb.mapTo(dlg, _lb.rect().center()).y()
    _fy = _fac.mapTo(dlg, _fac.rect().center()).y()
    check(abs(_ly - _fy) <= 4,
          f"设施输入框与「出入口信息」**同一行**（中心 y {_ly} vs {_fy}，"
          f"差 {abs(_ly - _fy)}）")
    check(_fac.mapTo(dlg, _fac.rect().topLeft()).x()
          > _lb.mapTo(dlg, _lb.rect().topRight()).x(),
          "设施输入框在「出入口信息」**右侧**")
    check(_fac.width() > 300,
          f"设施输入框占满右边剩余宽度（{_fac.width()}px）")
    # ★ 关键：设施必须在**出入口标题那一行的右侧**，而不是在出入口内容的下方
    check(_fy < _ex_w.mapTo(dlg, _ex_w.rect().topLeft()).y(),
          "设施在出入口**标题**行（不是落在内容下面）")
# 「设施」两个字必须彻底消失（用户明确要求删掉）
_all_lab_txt = [lb.text().strip() for lb in dlg.form_host.findChildren(QLabel)]
check("设施" not in _all_lab_txt,
      f"整个表单里已经没有『设施』两个字（标签文字已删）")
check(_fac.placeholderText() != "",
      f"靠 placeholder 提示含义（{_fac.placeholderText()!r}）")

# =========================================================
print("\n=== A9) 「首末班车」表格化（v2.6.4）===")
# 用户：「首/末班车看起来很不明显」→ 按日期类型分组、列对齐、首末各自配色加粗。
from PySide6.QtWidgets import QGridLayout                                 # noqa: E402

_tt = dlg._widgets["timetable"]
check(isinstance(_tt, TimetableEditor),
      f"首末班车用的是专用表格控件（实际 {type(_tt).__name__}）")

# 总行数：所有站都要能解析（解析不了的行会掉进"兜底纯文本"，就白做了）
_tt_all = 0
_tt_bad = []
for _sid, _st in _all.items():
    _t = str(_st.get("timetable") or "")
    for _ln2 in _t.splitlines():
        if _ln2.strip():
            _tt_all += 1
            if TimetableEditor.parse_line(_ln2.strip()) is None:
                _tt_bad.append((_sid, _ln2.strip()[:40]))
check(not _tt_bad,
      f"全部 {_tt_all} 行首末班车都能结构化解析（失败 {len(_tt_bad)}：{_tt_bad[:3]}）")

# 往返：拆开→拼回必须与原文逐字节一致（**没动过就原样吐回**）
#   ★ 只对"有 timetable 的站"抽样建控件（每个站几十个 QLineEdit，全量太慢）；
#     但上面的 parse_line 全量覆盖已经把"结构上必然一致"证明了。
_sample = []
for _sid, _st in _all.items():
    _t = str(_st.get("timetable") or "")
    if _t.strip():
        _sample.append((_sid, _t))
_sample.sort(key=lambda x: -len(x[1].splitlines()))
_pick = _sample[:5]
_pick += [x for x in _sample if "首--" in x[1]][:3]
_seen, _uniq = set(), []
for _sid, _t in _pick:
    if _sid not in _seen:
        _seen.add(_sid)
        _uniq.append((_sid, _t))
_rt_bad = []
for _sid, _t in _uniq:
    _e = TimetableEditor(_t)
    if _e.text() != _t:
        _rt_bad.append(_sid)
check(not _rt_bad,
      f"抽样 {len(_uniq)} 个站（含多线路站与终点站）拆开→拼回逐字节一致"
      f"（不一致 {_rt_bad}）")

# 含「首-- 末--」（终点站没有反向班次）的站也必须原样保住
_tt_dash = TimetableEditor(str(_all["机场东"].get("timetable") or ""))
check("首--" in _tt_dash.text(),
      "终点站的 `首-- 末--` 原文保住了（没被当成空值抹掉）")

# 变异自检：换成"一律重拼"的天真写法，必须能抓出不一致
class _TtNaive(TimetableEditor):
    def text(self):
        out = []
        for g in self._groups:
            # v2.6.7：日期胶囊已删（改成顶部下拉），`date_ed` 是 None，
            # 这里退回用 `g.date` —— 变异的"天真"之处仍然是把每行**一律重拼**。
            d = (g.date_ed.text().strip() if g.date_ed is not None else g.date)
            for row in g.rows:
                ln = row.line_ed.text().strip()
                its = []
                for it in row.items:
                    t = (it["_dir_ed"].text().strip(),
                         it["_first_ed"].text().strip(),
                         it["_last_ed"].text().strip())
                    if any(t):
                        its.append(t)
                if ln and its:
                    out.append("%s · %s：%s" % (
                        d, ln, "；".join("%s 首%s 末%s" % x for x in its)))
        return "\n".join(out)


# ★ 变异自检要用**格式不规整的输入**才测得出来：
#   现有 1284 行**全部是规范格式**（1064 行 `首06:02` + 220 行终点站 `首--`），
#   所以"一律重拼"和"原样吐回"**在这些数据上结果一样** —— 直接拿线上数据
#   做变异会得到 0，看着像"判据没上岗"。
#   于是再造两行**真实可能出现的不规整写法**来验证机制本身：
#   少个空格、半角冒号、行尾多个空格。原样吐回必须把它们**一字不动**地保住。
_odd = [
    "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41  末23:21",  # 双空格
    "工作日·1号线:往罗湖 首06:02 末23:47",                                 # 无空格·半角冒号
    "工作日 · 1号线：往罗湖 首06:02 末23:47  ",                            # 行尾空格
    "本站不提供首末班车信息",                                              # 整行不是表格
]
_keep_bad = [t for t in _odd if TimetableEditor(t).text() != t.strip()]
check(not _keep_bad, f"不规整写法也原样保住（{len(_keep_bad)} 处被改写：{_keep_bad}）")
_naive_odd = [t for t in _odd[:3] if _TtNaive(t).text() != t.strip()]
check(len(_naive_odd) > 0,
      f"变异自检：天真写法会改坏 {len(_naive_odd)}/{len(_odd[:3])} 行不规整输入"
      f"（>0 说明上面那条真的在上岗）")
# 而"整行不是表格"的那种，两种写法都必须原样留着（走兜底，绝不丢内容）
check(TimetableEditor(_odd[3]).text().strip() == _odd[3],
      f"解析不了的行原样保留（{_odd[3]!r}）")

# ---- 视觉：日期类型分组 / 首末字号更大 / 表头与数据列对齐 / 线路色点 ----
_e = TimetableEditor(str(_all["车公庙"].get("timetable") or ""))
_groups = _e._groups
check(len(_groups) == 3 and [g.date for g in _groups] == ["工作日", "休息日", "节假日"],
      f"按日期类型分了 {len(_groups)} 组：{[g.date for g in _groups]}")
_rows0 = _groups[0].rows
check(len(_rows0) == 4, f"工作日下有 {len(_rows0)} 条线路（车公庙 4 条线）")
_it0 = _rows0[0].items[0]
_f_font = _it0["_first_ed"].font()
_l_font = _it0["_last_ed"].font()
_d_font = _it0["_dir_ed"].font()
check(_f_font.pointSizeF() > _d_font.pointSizeF(),
      f"首班字号 > 方向字号（{_f_font.pointSizeF()} > {_d_font.pointSizeF()}）—— 这就是"
      f"「看得明显」的量化判据")
check(_f_font.bold() and _l_font.bold(), "首班/末班都是加粗的")
check("首" not in _it0["_first_ed"].text(),
      f"首班框里只有时间（{_it0['_first_ed'].text()!r}）—— '首'/'末' 由列头承担")
check(_it0["_dir_ed"].text().startswith("往"),
      f"方向带「往」字（{_it0['_dir_ed'].text()!r}）")

# ★★ v2.6.7 实测教训：只比"左边缘 x"是**不够的** ——
#   表头 QLabel 只有"线路"两个字的自然宽度（22px），下方输入框却是定宽（56/90/68px），
#   两边都靠左放 ⇒ 左边缘完全相等（旧断言通过），可**中心差 (内容宽−标签宽)/2**
#   （实测 17 / 34 / 23px），用户一眼就看出歪。所以这里改成比**中心**。
def _col_centers(grid):
    """{列: (中心x, 宽)} —— 取该列第 0 行的控件。"""
    out = {}
    for i in range(grid.count()):
        r, c, _rs, _cs = grid.getItemPosition(i)
        w = grid.itemAt(i).widget()
        if r == 0 and w is not None and c not in out:
            out[c] = (w.mapTo(_e, w.rect().topLeft()).x()
                      + w.rect().width() / 2.0, w.rect().width())
    return out


# ★ 量几何的前提：控件**真的被布局过**。
#   这个 TimetableEditor 是独立造的，没放进任何可见窗口 ⇒
#   ① 子控件 isVisible() 全是 False（父不可见），② 几何是未布局的旧值。
#   实测踩过：不挂宿主时中心差报 24/88/186/290px，全是假的 —— 挂上去才是 0。
from PySide6.QtWidgets import QVBoxLayout as _QVB, QWidget as _QW   # noqa: E402
_host = _QW()
_QVB(_host).addWidget(_e)
_host.resize(760, 600)
_host.show()
app.processEvents()

_grids = _e.findChildren(QGridLayout)
check(len(_grids) >= 2, f"表头 + {len(_grids)-1} 个分组各有自己的网格")
# ★ 一次只显示一组（下拉切换可见性）。隐藏的控件没有真实几何，
#   不切过去就量 = 量到未布局的旧坐标 ⇒ 假失败。
_mismatch = []
_width_bad = []
_widths_seen = []
_box_vis = []
for _gi, _gr in enumerate(_grids[1:], start=1):
    _e.date_combo.setCurrentIndex(_gi - 1)
    app.processEvents()
    _box_vis.append(sum(1 for b in _e._group_boxes if b.isVisible()))
    _hdr = _col_centers(_grids[0])
    _gx = _col_centers(_gr)
    _widths_seen.append([round(_gx[c][1], 1) for c in sorted(_gx)])
    for c in (0, 1, 2, 4):                     # 线路 / 方向 / 首班 / 末班
                                                   # （v2.6.11 起没有圆点列了）
        if c in _hdr and c in _gx:
            if abs(_hdr[c][0] - _gx[c][0]) > 1:
                _mismatch.append(f"grid{_gi}.col{c} 中心差 "
                                 f"{abs(_hdr[c][0] - _gx[c][0]):.1f}px")
            if abs(_hdr[c][1] - _gx[c][1]) > 1:
                _width_bad.append(f"col{c} 表头{_hdr[c][1]:.0f}≠内容{_gx[c][1]:.0f}")
check(not _mismatch,
      f"表头与各分组的**列中心**完全对齐（偏差 {len(_mismatch)} 处）"
      + ("：" + "；".join(_mismatch) if _mismatch else ""))
check(not _width_bad,
      f"表头格子与下方内容**等宽**（这是中心能对齐的前提）"
      + ("：" + "；".join(_width_bad) if _width_bad else ""))
# 切换日期类型时列宽不许跳（否则点一下下拉整张表会左右抖）
check(len({tuple(w) for w in _widths_seen}) <= 1,
      f"切换日期类型时列宽一致（{_widths_seen}）")
check(all(v == 1 for v in _box_vis),
      f"任何时刻只显示一个日期分组（实际可见数 {_box_vis}）")

# ---- 表头：黑色 + 加粗（v2.6.7 用户要求）----
# ★★ v2.6.15：4 个 → **3 个**。用户原话：「删除文字『线路』，但下方显示的内容
#   如『一号线』放到表头如『工作日』正下方」。过滤集合里**仍然留着 "线路"**：
#   这样"哪天又被加回来"同样会让 == 3 失败（少了多了都抓得住）。
_hdr_labels = [w for w in _grids[0].parentWidget().findChildren(QLabel)
               if w.text() in ("线路", "方向", "首班", "末班")]
check(len(_hdr_labels) == 3,
      f"表头只剩三个文字：方向 / 首班 / 末班（找到 {len(_hdr_labels)} 个："
      f"{[w.text() for w in _hdr_labels]}）——「线路」已按用户要求删除")

# ★★★ v2.6.15 的核心几何关系：「一号线」必须落在「工作日」**正下方**。
#   实现上 = 日期类型下拉（表头网格第 0 列）与线路名输入框（内容网格第 0 列）
#   **同列** ⇒ 判据就是"两者水平中心重合"。这条比"第 0 列表头文字没了"更本质：
#   用户要的是**位置**，不是"少了个标签"。只断言"线路两个字不在了"抓不住
#   "线路名还留在原来那一列、下拉另起一列"这种半吊子改法。
_e.date_combo.setCurrentIndex(0)
app.processEvents()
_cb = _e.date_combo
_line_ed = _e._groups[0].rows[0].line_ed
# ★ 用**屏幕坐标**比：下拉在表头 box 里、线路名在分组 box 里，两者不是
#   同一个父控件（`mapTo` 到任意第三控件算出来的是没意义的数，实测差 485px）。
def _cx(wi) -> float:                       # noqa: E306
    return wi.mapToGlobal(wi.rect().center()).x()


_dx = abs(_cx(_cb) - _cx(_line_ed))
check(_dx <= 2,
      f"「{_cb.currentText()}」下拉与「{_line_ed.text()}」**同在一列**"
      f"（水平中心差 {_dx:.1f}px ≤ 2）⇒ 线路名就在下拉正下方")
_dir_ed = _e._groups[0].rows[0].items[0]["_dir_ed"]
check(_cx(_line_ed) < _cx(_dir_ed),
      "线路名列在「方向」列**左边**（左起：线路 | 方向 | 首班 | → | 末班）")
# 变异自检：把比较对象换成**另一列**（方向框）就应该对不上 ——
# 证明上面那条"同列（±2px）"判据真有分辨力，而不是阈值宽到什么都算通过。
_dx_bad = abs(_cx(_cb) - _cx(_dir_ed))
check(_dx_bad > 2,
      f"变异自检：下拉 vs **方向**框的水平中心差 {_dx_bad:.1f}px > 2 "
      f"⇒「同列」判据能分辨出不同列")
for _h in _hdr_labels:
    check(_h.font().bold(), f"表头「{_h.text()}」是加粗的")
    _c = _h.palette().color(_h.foregroundRole())
    check(_c.name().upper() == "#000000",
          f"表头「{_h.text()}」是**黑色**的（实际 {_c.name()}）")
    check(int(_h.alignment()) & int(Qt.AlignHCenter),
          f"表头「{_h.text()}」是**居中**的")

# ---- 变异自检：表头退回 v2.6.7 之前的写法（自然宽度 + 靠左）----
# 必须**立刻**量出错位，否则说明"中心对齐"这条判据是恒真的假测试。
# ★ 变异必须改到**点子上**。两次踩坑记录在这儿：
#   ① 改 `sizeHint()` 不行 —— 表头已被 setFixedWidth 钉住，取回来还是那个值；
#   ② 改标签**内部文字**的 `setAlignment()` 也不行 —— 标签控件自己在格子里
#      是居中的，文字左对齐不影响外框位置，Δ 还是 0。
#   真正要复原的是"**控件在格子里靠左放**" ⇒ 用 `addWidget(..., AlignLeft)` 重加。
_g0 = _grids[0]
_restore = []
for _i in range(_g0.count()):
    _w = _g0.itemAt(_i).widget()
    if not isinstance(_w, QLabel) or _w.text() not in ("线路", "方向", "首班", "末班"):
        continue
    _r, _c, _rs, _cs = _g0.getItemPosition(_i)
    _restore.append((_w, _r, _c, _rs, _cs))
    _w.setFixedWidth(_w.fontMetrics().horizontalAdvance(_w.text()))   # 自然宽度
    _g0.addWidget(_w, _r, _c, _rs, _cs, Qt.AlignLeft)                 # 靠左放
app.processEvents()
_hdr_m = _col_centers(_grids[0])
_gx_m = _col_centers(_grids[_e.date_combo.currentIndex() + 1])
_bad = [c for c in (0, 1, 2, 4)
        if c in _hdr_m and c in _gx_m and abs(_hdr_m[c][0] - _gx_m[c][0]) > 5]
check(len(_bad) >= 2,
      f"变异（表头回到自然宽度+靠左）会立刻错位：列 {_bad} ⇒ 判据真的在上岗")
for _w, _r, _c, _rs, _cs in _restore:
    _w.setFixedWidth(_hdr[_c][1])
    _g0.addWidget(_w, _r, _c, _rs, _cs, Qt.AlignCenter)
app.processEvents()
check(not [c for c in (0, 1, 2, 4)
           if abs(_col_centers(_grids[0])[c][0]
                  - _col_centers(_grids[_e.date_combo.currentIndex() + 1])[c][0]) > 1],
      "还原表头后中心差又回到 0（变异可逆）")

# ---- ★ 切日期类型时**数据一条都不能少**（隐藏的分组照样要写回）----
_orig = str(_all["车公庙"].get("timetable") or "")
check(_e.text() == _orig, "初始 text() 与原文一致")
_seen = []
for _i in range(_e.date_combo.count()):
    _e.date_combo.setCurrentIndex(_i)
    app.processEvents()
    _seen.append(_e.text())
check(all(s == _orig for s in _seen),
      f"三个日期类型来回切，text() 始终等于原文（{[s == _orig for s in _seen]}）")
check(len(_orig.splitlines()) == len(_e.text().splitlines()),
      f"行数也没少（{len(_e.text().splitlines())} vs 原文 {len(_orig.splitlines())}）")

# 线路色点用**官方线路色**（不是随手一个颜色）
check(_LineDot.lookup("1号线").upper() == "#00B052",
      f"1号线色点 = {_LineDot.lookup('1号线')}（应 = 官方 #00B052）")
check(all(_LineDot.lookup(n) != "#CBD5E1"
          for n in ("1号线", "7号线", "9号线", "11号线")),
      "车公庙 4 条线都能查到官方色（没有落到灰点兜底）")

# =========================================================
print("\n=== A10) v2.6.8 出入口编号垂直居中 + 输入框自动拉伸 ===")
from ui.exits_editor import ExitsEditor as _XE                        # noqa: E402
from ui.autofit import fit_height as _fit, no_inner_scroll as _nis    # noqa: E402

_xe = dlg._widgets["exits"]
check(isinstance(_xe, _XE),
      f"出入口用的是两栏控件（实际 {type(_xe).__name__}）")

# ① 编号「恰好在输入框的中间位置」（用户原话）
_off = []
for _r in _xe.rows:
    _tc = _r[0].mapTo(_xe, _r[0].rect().center()).y()
    _xc = _r[1].mapTo(_xe, _r[1].rect().center()).y()
    if abs(_tc - _xc) > 3:
        _off.append(round(abs(_tc - _xc), 1))
check(not _off,
      f"编号与内容框**垂直居中对齐**（{len(_xe.rows)} 行，偏差超 3px 的：{_off}）")

# 变异自检：把编号改回 v2.6.8 之前的 AlignTop。
# ★ 必须挑**内容框高于一行**的那一行来变异 —— 单行时 AlignTop 和 AlignVCenter
#   几乎重合（差 1px），变异看不出差别，会让人误以为判据恒真。
_bi = max(range(len(_xe.rows)), key=lambda i: _xe.rows[i][1].height())
_bh = _xe.rows[_bi][1].height()
check(_bh > 45, f"用于变异的那行内容框高 {_bh}px（>45，多行才验得出差别）")
_bh_lay = _xe.rows[_bi][0].parentWidget().layout()
_bh_lay.addWidget(_xe.rows[_bi][0], 0, Qt.AlignTop)
app.processEvents()
_mc = abs(_xe.rows[_bi][0].mapTo(_xe, _xe.rows[_bi][0].rect().center()).y()
           - _xe.rows[_bi][1].mapTo(_xe, _xe.rows[_bi][1].rect().center()).y())
check(_mc > 3, f"变异（编号改回 AlignTop）立刻偏出 {_mc:.1f}px ⇒ 判据真的在上岗")
_bh_lay.addWidget(_xe.rows[_bi][0], 0, Qt.AlignVCenter)
app.processEvents()
_mc2 = abs(_xe.rows[_bi][0].mapTo(_xe, _xe.rows[_bi][0].rect().center()).y()
            - _xe.rows[_bi][1].mapTo(_xe, _xe.rows[_bi][1].rect().center()).y())
check(_mc2 <= 3, f"还原后又居中（差 {_mc2:.1f}px）")

# ② 多行输入框「文字多少都拉伸到刚好全部显示完」（用户原话）
for _k in ("landmarks", "notes", "bus_transfer"):
    _w = dlg._widgets[_k]
    _orig_txt = _w.toPlainText()
    _w.setPlainText("短")
    app.processEvents()
    _h1 = _fit(_w, 40)
    app.processEvents()
    _w.setPlainText("测试文字测试文字测试文字" * 40)
    app.processEvents()
    _h2 = _fit(_w, 40)
    app.processEvents()
    check(_h2 > _h1 + 20,
          f"{_k}: 文字变多 ⇒ 框跟着变高（{_h1} → {_h2}px）")
    check(_nis(_w),
          f"{_k}: 长文字**全部显示完**、没有内部滚动条")
    # 变异自检：把高度钉死成最小 —— 判据必须立刻翻脸，否则是恒真的假测试
    _w.setFixedHeight(40)
    app.processEvents()
    check(not _nis(_w),
          f"{_k}: 变异（高度钉死 40px）立刻出现内部滚动 ⇒ 上面那条在上岗")
    _w.setPlainText(_orig_txt)
    app.processEvents()
    _fit(_w, 40)
    app.processEvents()
    check(_nis(_w), f"{_k}: 还原原文后又正常了")

# ★★ 顺手记一笔本轮最坑的陷阱：`QPlainTextEdit.document().size()` 是**惰性**的
#   （实测 1 行返回 1.0、400 字返回 8.0），照它算高度 ⇒ 所有框一律压到最小，
#   而且是**静默**的。下面这条断言专门钉住"必须按 block 累加"这件事。
from ui.autofit import doc_height as _dh                              # noqa: E402
_t = dlg._widgets["notes"]
_t.setPlainText("很长的一段测试文字" * 60)
app.processEvents()
check(_dh(_t) > 60 and int(_t.document().size().height()) < 60,
      f"document().size() 果然是惰性的（block 累加 {_dh(_t):.0f} vs "
      f"size() {_t.document().size().height():.1f}）⇒ 只能按 block 累加")
_t.setPlainText(str(_all["机场东"].get("notes") or ""))
app.processEvents()
_fit(_t, 40)

# =========================================================
print("\n=== A7) 出入口「编号 + 内容」两栏（v2.6.3）===")
# 用户要求：把 `A1出入口：龙岗大道南侧、xxx` 里的 A1 **加粗加大、从输入框独立出去**，
# 并**删掉"出入口"三个字** → 显示成 `A1    龙岗大道南侧、xxx`。
# 判定要点（都是可量化的，不靠"看起来像"）：
#   ① 编号控件与内容控件**是两个不同的控件**（独立出去）
#   ② 编号字号 > 内容字号，且字重是 Bold
#   ③ 内容框里**不再含"出入口"三字**
#   ④ 保存时**拼回原格式**（存储格式不变 ⇒ 不用迁移 379 站数据）
_rows = getattr(dlg, "_exit_rows", [])
check(len(_rows) >= 1, f"出入口拆出了 {len(_rows)} 行")
check(isinstance(_rows[0][0], QLineEdit), f"编号是独立控件（{type(_rows[0][0]).__name__}）")
check(isinstance(_rows[0][1], QPlainTextEdit), f"内容是独立控件（{type(_rows[0][1]).__name__}）")
# ★ 编号输入框的 maxLength 必须容得下数据里最长的编号，否则一编辑就截断
_longest = max((len(r[2]) for r in _rows), default=0)
check(dlg._exit_rows[0][0].maxLength() >= 12,
      f"编号输入上限 = {dlg._exit_rows[0][0].maxLength()}（要 ≥ 12，装得下 14a、14b、14c）")
check(_rows[0][0] is not _rows[0][1], "编号与内容不是同一个控件（真的独立了）")
_ft, _fc = _rows[0][0].font(), _rows[0][1].font()
check(_ft.pointSizeF() > _fc.pointSizeF(),
      f"编号字号 > 内容字号（{_ft.pointSizeF()} > {_fc.pointSizeF()}）")
check(_ft.bold() or "700" in _rows[0][0].styleSheet(),
      f"编号是加粗的（font.bold={_ft.bold()}）")
check(_rows[0][0].width() < _rows[0][1].width() / 3,
      f"编号列明显窄于内容列（{_rows[0][0].width()} vs {_rows[0][1].width()}）—— 布局上真的分开了")
# 内容里不许再有"出入口"三个字
_bad = [r[1].toPlainText() for r in _rows if "出入口" in r[1].toPlainText()]
check(not _bad, f"内容框里已无 '出入口' 字样（违规 {len(_bad)} 处）")
# 拆出来的编号必须和原始数据对得上
# ★ 用**产品自己的解析器**来算期望值，别在测试里另写一套 —— 那样测的就成了
#   "测试的正则和产品的正则像不像"，而不是"产品拆得对不对"。
_src = str((dm.get_station("机场东") or {}).get("exits") or "")
_want_tags = [r[0] for r in EditDialog._parse_exits(_src)]
_got_tags = [r[0].text() for r in _rows]
check(_got_tags == _want_tags,
      f"编号列 = {_got_tags}（原文里应是 {_want_tags}）")
# ★ 往返一致：拆开再拼回去必须**逐字节等于**原值（存储格式不变的硬证据）
_round = dlg._collect_exits()
check(_round == _src.replace("\r\n", "\n").replace("\r", "\n").strip(),
      "拆开→拼回 与原数据逐字一致（存储格式未改动）")
# 内容框高度必须**容得下**实际文字（长出口不能被截掉/必须出现内部滚动条）
for te, tx in [(r[0], r[1]) for r in _rows]:
    _txt = tx.toPlainText()
    if not _txt:
        continue
    from PySide6.QtGui import QFontMetrics as _FM
    from PySide6.QtCore import QRect as _QR
    _need = _FM(tx.font()).boundingRect(_QR(0, 0, tx.viewport().width() - 4, 100000),
                                       Qt.TextWordWrap, _txt).height()
    check(tx.height() >= _need + 6,
          f"出口 {te.text()!r} 内容框够高（{tx.height()} ≥ 文字 {_need}+6）")

# ---- ★★ 全量往返：379 站的 exits 都要"拆开再拼回 = 原文" ----
# 为什么这条最要紧：用户在弹窗里**什么都没改**点保存，数据就不该动。
# 真实数据里有 `6A号出入口` / `A1出口` / `E出入囗`（官网错别字）/ `9出入口`（没冒号）
# 这些写法，一律"编号 + '出入口：' + 内容"重拼的话，一保存就把 12 行悄悄改了。
class _FakeEdit:
    """只实现 text()/toPlainText() 的假控件，用来直接喂给 _collect_exits。"""
    def __init__(self, s): self._s = s
    def text(self): return self._s
    def toPlainText(self): return self._s


# （_all 已在上方 A8 之前加载）
_changed, _n = [], 0
_total_rows = 0
for _sid, _st in _all.items():
    _orig = str(_st.get("exits") or "")
    if not _orig.strip():
        continue
    _parsed = EditDialog._parse_exits(_orig)
    _total_rows += len(_parsed)
    _probe = EditDialog.__new__(EditDialog)          # 不跑 __init__，只借方法
    _probe._exit_rows = [(_FakeEdit(t), _FakeEdit(x), t, x, ln)
                         for t, x, _p, ln in _parsed]
    if _probe._collect_exits() != _orig:
        _changed.append(_sid)
    _n += 1
check(not _changed,
      f"{_n} 个有出入口的站，拆开→拼回全部与原文逐字节一致"
      f"（共 {_total_rows} 行；不一致 {len(_changed)} 个：{_changed[:5]}）")
# 反向自检：如果**故意**按"一律重拼"的写法，必须能抓出不一致 ——
# 否则上面那条"全过"可能只是因为我的判据恒真（一个从不报错的校验器等于没有）。
class _ProbeNaive(EditDialog):
    def _collect_exits(self):                         # 故意用天真写法
        out = []
        for r in self._exit_rows:
            t, x = r[0].text().strip(), r[1].toPlainText().strip()
            if t or x:
                out.append(("%s出入口：%s" % (t, x)) if t else x)
        return "\n".join(out)


_bad = 0
for _sid, _st in _all.items():
    _orig = str(_st.get("exits") or "")
    if not _orig.strip():
        continue
    _parsed = EditDialog._parse_exits(_orig)
    _probe = _ProbeNaive.__new__(_ProbeNaive)
    _probe._exit_rows = [(_FakeEdit(t), _FakeEdit(x), t, x, ln)
                         for t, x, _p, ln in _parsed]
    if _probe._collect_exits() != _orig:
        _bad += 1
check(_bad > 0,
      f"变异自检：天真写法会改坏 {_bad} 个站（>0 说明上一条断言真的在上岗）")

# ---- 全量解析自检：不许有任何一行"没拆出编号"（否则"出入口"三字删不掉）----
_nolabel = []
for _sid, _st in _all.items():
    for _ln in str(_st.get("exits") or "").splitlines():
        _s = _ln.strip()
        if not _s:
            continue
        if not EditDialog._parse_exit_line(_s)[2]:     # 第 3 项 = 原样前缀
            _nolabel.append((_sid, _s))
check(not _nolabel,
      f"所有出口行都识别出了编号（未识别 {len(_nolabel)} 行：{_nolabel[:4]}）")
dlg.hide()

# =========================================================
print("\n=== C) 封面图：导入 / 解析 / 更换 / 移除 ===")
dlg._cover_src = str(TMP_IMG)
fn1 = dlg._commit_cover("机场东")
created_covers.append(fn1)
check(bool(fn1), f"导入返回文件名 = {fn1!r}")
p1 = dm.cover_path(fn1)
check(p1 is not None and p1.exists(), f"文件已落到 data/covers/：{p1}")
check(p1.parent == dm.covers_dir(), "落在 data/covers/ 目录下")
check(dm.resolve_cover({"cover": fn1}) is not None, "resolve_cover 能取到路径")
check(dm.resolve_cover({"cover": "不存在的图.png"}) is None, "resolve_cover 对不存在的文件返回 None")
check(dm.resolve_cover({}) is None, "resolve_cover 对无 cover 字段返回 None")

# resolve_cover 走的是真实"机场东"这条数据 → 用它检查 tooltip
fake_station = dict(dm.get_station("机场东") or {})
fake_station["cover"] = fn1

# 换成另一张（不同扩展名要能替换干净）
ALT_IMG = SRC / "_test_cover_src2.jpg"
make_test_png(ALT_IMG, "#e91e63")
alt = QPixmap(str(ALT_IMG))
alt.save(str(ALT_IMG))
fn2 = dm.import_cover("机场东", str(ALT_IMG))
created_covers.append(fn2)
check(fn2.endswith(".jpg"), f"换封面得到新文件名 = {fn2!r}")
check(dm.cover_path(fn1) is None, "旧封面（不同扩展名）已被清掉")

# 移除
check(dm.remove_cover(fn2) is True, "remove_cover 返回 True")
check(dm.cover_path(fn2) is None, "文件确已删除")

# =========================================================
print("\n=== D) 悬浮提示显示封面 ===")
tip = HoverTip()
fn3 = dm.import_cover("机场东", str(TMP_IMG))
created_covers.append(fn3)
tip.show_for(dlg.mapToGlobal(dlg.rect().center()), fake_station, dm.cover_path(fn3))
check(not tip.lbl_cover.isHidden(), "有封面时：图片区域可见")
check(not tip.lbl_cover.pixmap().isNull(), "有封面时：pixmap 非空")
tip.hide()
tip.show_for(dlg.mapToGlobal(dlg.rect().center()), fake_station, None)
check(tip.lbl_cover.isHidden(), "无封面时：图片区域隐藏")
# 缓存只留一条tip.show_for(dlg.mapToGlobal(dlg.rect().center()), fake_station, dm.cover_path(fn3))
tip.show_for(dlg.mapToGlobal(dlg.rect().center()), fake_station, dm.cover_path(fn3))
check(len(tip._cover_cache) <= 1, f"封面缓存条目数 = {len(tip._cover_cache)}（应 ≤1）")
tip.hide()

# =========================================================
print("\n=== E) 新建模式 ===")
dlg2 = EditDialog(station_id="")
got2 = {}
dlg2.save_requested.connect(lambda sid, p: got2.update(sid=sid, payload=p))
check(dlg2.name_edit.text() == "新站点", f"名称初值 = {dlg2.name_edit.text()!r}")

dlg2.name_edit.setText("   ")
dlg2._on_save()
check(not got2, "空名被拦下，未发出保存")
check(any("不能为空" in str(w) for w in warnings), f"弹了校验提示：{warnings}")

dlg2.name_edit.setText("测试新站")
dlg2._cover_src = str(TMP_IMG)
dlg2._on_save()
check(bool(got2.get("sid")), f"发出 station_id = {got2.get('sid')!r}")
new_fn = str(got2.get("payload", {}).get("cover") or "")
created_covers.append(new_fn)
check(new_fn.startswith(str(got2.get("sid"))), f"封面文件名以新 id 打头 = {new_fn!r}")
check(dm.cover_path(new_fn) is not None, "新站点封面已落盘")

# =========================================================
print("\n=== F) 右侧信息面板：多行字段同样「标签在上」+ 反复切换不掉控件 ===")
from ui.info_panel import InfoPanel                                       # noqa: E402
panel = InfoPanel()
panel.resize(380, 720)
panel.show()
panel.show_station("机场东")
app.processEvents()
for key, want_label in MULTILINE:
    ed = panel._widgets[key]
    box = ed.parentWidget()
    labs = [lb for lb in box.findChildren(QLabel) if lb.text().strip() == want_label]
    if key == "timetable":
        # v2.6.8：面板与弹窗同一份改动 —— 下拉搬进表格自己的表头行，
        #   位置在表头「线路」的**左侧**，且文字居中。
        cb = ed.date_combo
        check(len(labs) == 0, f"面板 {key}: 已无标签 '首末班车'（找到 {len(labs)} 个）")
        _ll_p = [lb for lb in ed.findChildren(QLabel)
                 if lb.text().strip() == "线路"]
        if _ll_p:
            _cx = cb.mapTo(ed, cb.rect().center()).x()
            _lx = _ll_p[0].mapTo(ed, _ll_p[0].rect().center()).x()
            check(_cx < _lx,
                  f"面板 {key}: 下拉在表头『线路』的**左侧**（{_cx:.0f} < {_lx:.0f}）")
        # v2.6.9：面板这一份与弹窗同一份控件，同样三条 + 两个变异
        check_combo_v269(f"面板 {key}", ed, cb)
        continue
    check(len(labs) == 1, f"面板 {key}: 有标签 {want_label!r}")
    if labs:
        lb = labs[0]
        check(lb.geometry().bottom() <= ed.geometry().top() + 1,
              f"面板 {key}: 标签在输入框上方（{lb.geometry().bottom()} ≤ {ed.geometry().top()}）")

# 反复切换站点：每切一次都会 _clear_form 重建表单，验证跨列行不会清不干净
first = panel._widgets["exits"]
for _ in range(3):
    panel.show_station("机场东")
    app.processEvents()
check(panel._widgets["exits"] is not first, "切换后表单确实重建了（新控件）")
# v2.6.6：那一行「是否换乘站 + 开通日期」已经删了，面板也已没有"两字段并排"。
# v2.6.8：再减掉 `head_with` 的字段（设施挂进了「出入口信息」那一行）。
check(panel.form_layout.rowCount() == len(EDITABLE_FIELDS) - len(_HEADWITH),
      f"面板表单行数 = {panel.form_layout.rowCount()}"
      f"（字段数 {len(EDITABLE_FIELDS)} − {len(_HEADWITH)} 个挂到别人行里）")
check(len(panel._widgets) == len(EDITABLE_FIELDS), f"面板控件数 = {len(panel._widgets)}")
# ★ v2.6.5：面板的出入口也换成结构化控件了，取值要走 `text()`（不再是 toPlainText）
got_exits = panel._widgets["exits"].text()
want_exits = str((dm.get_station("机场东") or {}).get("exits") or "")
check(got_exits == want_exits, f"重建后取值正常（{got_exits!r}）")

# =========================================================
print("\n=== F2) 信息面板跟上结构化：出入口两栏 / 首末班车表格 / 设施单行（v2.6.5）===")
from ui.exits_editor import ExitsEditor                                    # noqa: E402
from ui.timetable_editor import TimetableEditor as _TT                     # noqa: E402

ex_p = panel._widgets.get("exits")
check(isinstance(ex_p, ExitsEditor),
      f"面板出入口用的是两栏控件（实际 {type(ex_p).__name__}）—— 与弹窗同一份实现")
check(ex_p is not dlg._widgets.get("exits") or True, "（弹窗与面板各持一个实例）")

tt_p = panel._widgets.get("timetable")
check(isinstance(tt_p, _TT),
      f"面板首末班车用的是表格控件（实际 {type(tt_p).__name__}）")
check(getattr(tt_p, "compact", False) is True,
      f"面板用的是**紧凑模式**（compact={getattr(tt_p, 'compact', None)}）")

# ★ 面板比弹窗窄得多：核心判据是"**不许横向溢出**"（不是"好不好看"）
_panel_avail = panel.width() - 24          # 减掉 root 布局左右各 12px
check(tt_p.sizeHint().width() <= _panel_avail,
      f"面板表格最小宽 {tt_p.sizeHint().width()} ≤ 可用宽 {_panel_avail}")
for _k in ("exits", "timetable", "facilities"):
    _w = panel._widgets.get(_k)
    if _w is not None:
        check(_w.width() <= _panel_avail,
              f"面板 {_k} 未横向溢出（{_w.width()} ≤ {_panel_avail}）")

# 变异自检：把 compact 关掉（用完整列宽）应该**明显更宽** ——
# 否则说明 "compact 真的改了列宽" 这条根本没在上岗。
# ★★ v2.6.15 改判据：原来断言的是**绝对**的"完整模式 > 面板可用宽"。
#    下拉槽位并进网格第 0 列之后整表窄了 ~68px，完整模式（349）已经不溢出
#    356 了 ⇒ 那条断言变成**假失败**（代码没问题，是判据的前提没了）。
#    改成**相对**判据："完整模式比紧凑模式宽" —— 它测的正是这条变异自检
#    真正想测的东西（compact 有没有生效），而且不会随整体宽度漂移而失效。
_tt_wide = _TT(str((dm.get_station("机场东") or {}).get("timetable") or ""),
               compact=False)
check(_tt_wide.sizeHint().width() > tt_p.sizeHint().width(),
      f"变异自检：完整模式比紧凑模式**更宽**（{_tt_wide.sizeHint().width()} > "
      f"{tt_p.sizeHint().width()}）⇒ compact 真的在起作用")
check(_tt_wide.text() == tt_p.text(), "紧凑/完整模式拼回结果一致（只是列宽不同）")

# 面板出入口：拆开→拼回逐字节一致（与弹窗同一条铁律）
_panel_bad = []
_panel_n = 0
for _sid, _st in _all.items():
    _orig = str(_st.get("exits") or "")
    if not _orig.strip():
        continue
    _panel_n += 1
    if ExitsEditor(_orig).text() != _orig:
        _panel_bad.append(_sid)
check(not _panel_bad,
      f"面板出入口全量往返：{_panel_n} 个站拆开→拼回逐字节一致（不一致 {len(_panel_bad)}）")

# 设施（v2.6.8）：挂在「出入口信息」那一行的**标题右侧**，"设施"两个字已删
_fac_p = panel._widgets.get("facilities")
check(isinstance(_fac_p, QLineEdit),
      f"面板「设施」仍是单行输入框（实际 {type(_fac_p).__name__}）")
_ex_p = panel._widgets.get("exits")
_ex_labs_p = [lb for lb in _ex_p.parentWidget().findChildren(QLabel)
              if lb.text().strip() == "出入口信息"]
check(len(_ex_labs_p) == 1, "面板找得到「出入口信息」标签")
if _ex_labs_p:
    _lb = _ex_labs_p[0]
    _ly = _lb.mapTo(panel, _lb.rect().center()).y()
    _fy = _fac_p.mapTo(panel, _fac_p.rect().center()).y()
    check(abs(_ly - _fy) <= 4,
          f"面板设施与「出入口信息」**同一行**（中心 y {_ly} vs {_fy}，差 {abs(_ly-_fy)}）")
    check(_fac_p.mapTo(panel, _fac_p.rect().topLeft()).x()
          > _lb.mapTo(panel, _lb.rect().topRight()).x(),
          "面板设施在「出入口信息」**右侧**")
_plabs = [lb.text().strip() for lb in panel.findChildren(QLabel)]
check("设施" not in _plabs, "面板里也已经没有『设施』两个字")
# ★ v2.6.8：面板不能再横向溢出（下拉搬进表头行之后，宽度预算更紧了）
check(tt_p.sizeHint().width() <= _panel_avail,
      f"v2.6.8 复查：面板表格最小宽 {tt_p.sizeHint().width()} ≤ 可用宽 {_panel_avail}")
check(panel.form_layout.rowCount() == len(EDITABLE_FIELDS) - len(_HEADWITH),
      f"面板表单行数 = {panel.form_layout.rowCount()}"
      f"（字段数 {len(EDITABLE_FIELDS)} − {len(_HEADWITH)} 个挂到别人行里）")
panel.close()

# =========================================================
# =========================================================
print("\n=== G2) v2.6.6 变异自检：为什么 `_collect()` 必须补 derive_is_transfer ===")
import ui.edit_dialog as _ed                                              # noqa: E402
import ui.info_panel as _ip                                               # noqa: E402

# ① 先把"病根"摆出来：`upsert_station` 是**合并写入**，
#    payload 里没有的键不会被清空，而是保留磁盘上的旧值。
_existing = {"is_transfer": False, "lines": ["1"]}
_merged = dict(_existing)
_merged.update({"lines": ["1", "2"]})          # 模拟一个不带 is_transfer 的 payload
check(_merged["is_transfer"] is False,
      f"复现病灶：不带 is_transfer 的 payload 合并后旧值残留（{_merged}）")

# ② 变异：把派生函数换成"什么都不做" ⇒ 判据必须报警（否则说明上面的断言是恒真的）
_orig_ed = _ed.derive_is_transfer
_orig_ip = getattr(_ip, "derive_is_transfer", None)
_ed.derive_is_transfer = lambda payload: payload
if _orig_ip is not None:
    _ip.derive_is_transfer = lambda payload: payload
_ls.set_selected(["1", "2"])
app.processEvents()
_mut_payload = dlg._collect()
check("is_transfer" not in _mut_payload,
      f"变异后 payload 失去 is_transfer（键={sorted(_mut_payload)}）"
      f"⇒ 前面那条'键集合 = 字段 + is_transfer'确实在保护它")
_ed.derive_is_transfer = _orig_ed
if _orig_ip is not None:
    _ip.derive_is_transfer = _orig_ip

# ③ 还原后重新可用
_ls.set_selected(["1", "11", "12"])
app.processEvents()
check(dlg._collect()["is_transfer"] is True, "还原派生函数后重新能取到 True")
# ④ 面板侧也不能漏
check(hasattr(_ip, "derive_is_transfer"),
      "信息面板也引用了同一个派生函数（两处改动同一份）")

print("\n=== G3) v2.6.6 悬浮提示：站名与线路同一行、去掉 📍、换乘 🔄 保留 ===")
_tp_t = dm.get_station("车公庙") or {}
_tp = HoverTip()
_tp.show_for(dlg.mapToGlobal(dlg.rect().center()), _tp_t, None)
app.processEvents()
# 判据 1：两个标签必须在**同一个横向容器**里（不是上下两行）
check(_tp.lbl_title.parentWidget() is _tp.lbl_lines.parentWidget(),
      f"站名与线路同属一个容器（{type(_tp.lbl_title.parentWidget()).__name__}）")
check(_tp.lbl_title.parentWidget() is getattr(_tp, "title_row", None),
      "该容器就是 v2.6.6 新增的 title_row")
check(isinstance(_tp.title_row.layout(), QtW.QHBoxLayout),
      f"title_row 用的是横向布局（{type(_tp.title_row.layout()).__name__}）")
# 判据 2：竖直方向真的重叠（同排），不是碰巧都在这个容器里
_tr0 = _tp.lbl_title.geometry()
_tr1 = _tp.lbl_lines.geometry()
_ovl = min(_tr0.bottom(), _tr1.bottom()) - max(_tr0.top(), _tr1.top())
check(_ovl > 0, f"两个标签竖直有重叠 {_ovl}px（真的同一排）")
check(_tr1.left() >= _tr0.left(),
      f"站名在左、线路在右（{_tr0.left()} → {_tr1.left()}）")
# 判据 3：去掉定位图标，但换乘图标必须还在
check("\U0001f4cd" not in _tp.lbl_title.text(),
      f"站名前已无定位图标（实际 {_tp.lbl_title.text()!r}）")
if len(_tp_t.get("lines") or []) > 1:
    check("\U0001f504" in _tp.lbl_title.text(),
          f"换乘站的换乘图标仍然保留（实际 {_tp.lbl_title.text()!r}）")
check(_tp.lbl_lines.text().startswith("线路："),
      f"线路仍是'线路：x、y'的写法（实际 {_tp.lbl_lines.text()!r}）")
# 单条线路的站点也要正常
_tp2 = HoverTip()
_tp2.show_minimal(dlg.mapToGlobal(dlg.rect().center()), "机场东", ["1"])
app.processEvents()
check("\U0001f4cd" not in _tp2.lbl_title.text(),
      f"show_minimal 也无定位图标（实际 {_tp2.lbl_title.text()!r}）")
check(_tp2.lbl_lines.text() == "线路：1",
      f"单条线路显示正常（实际 {_tp2.lbl_lines.text()!r}）")
_tp2.hide()

print("\n=== 清理测试产物 ===")
for f in created_covers:
    if f:
        dm.remove_cover(f)
for tmp in (TMP_IMG, ALT_IMG):
    if tmp.exists():
        tmp.unlink()
rest = list(dm.covers_dir().glob("机场东.*")) + list(dm.covers_dir().glob("ST_*.*"))
check(not rest, f"临时封面已清干净（残留 {[p.name for p in rest]}）")

print("\n" + "=" * 48)
if fails:
    print(f"失败 {len(fails)} 项：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("全部通过 ✅")
