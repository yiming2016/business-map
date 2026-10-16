# -*- coding: utf-8 -*-
"""v2.7.14「看图模式」离屏探针（QT_QPA_PLATFORM=offscreen，绝不弹窗）。

覆盖：工具栏排布 / 模式切换 / 烘图 / 命中站点 / 站名只读 / 双击不弹框 /
png 落盘 / 拖动不白屏 / 切回编辑 / 缓存 / 变异自检。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

from PySide6.QtCore import QPoint, Qt                      # noqa: E402
from PySide6.QtGui import QColor                           # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402
from PySide6.QtTest import QTest                           # noqa: E402

app = QApplication(sys.argv)
from ui.main_window import MainWindow                      # noqa: E402
from ui import image_mode as IM                            # noqa: E402

PASS = FAIL = 0
FAILED = []


def ok(name, cond, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}" + (f"  ({info})" if info else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ✗ {name}  —— {info}")


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1600, 900)
win.show()
pump(20)
mv = win.map_view

# 关掉"启动自动生成"，本探针自己控制时机
win._view_autostart_done = True

# ======================================================================
print("===== ① 工具栏：模式按钮位置不动、编辑按钮在它左侧、⚙️ 在它右侧 =====")
tb = getattr(win, "toolbar", None)
acts = tb.actions() if tb is not None else []
idx_mode = acts.index(win.act_edit_mode) if win.act_edit_mode in acts else -1
idx_edit = [acts.index(a) for a in win._edit_actions if a in acts]
idx_gear = acts.index(win.act_img_settings) if win.act_img_settings in acts else -1
ok("①-1 模式按钮在工具栏里", idx_mode >= 0, f"index={idx_mode}")
ok("①-2 编辑类按钮**全部**排在模式按钮左侧",
   bool(idx_edit) and max(idx_edit) < idx_mode,
   f"编辑按钮最大 index={max(idx_edit) if idx_edit else None} / 模式 {idx_mode}")
ok("①-3 ⚙️ 紧挨模式按钮右侧", idx_gear == idx_mode + 1, f"gear={idx_gear}")
ok("①-4 初始文字 = 「✎ 编辑模式」（当前是看图，点它去编辑）",
   "编辑模式" in win.act_edit_mode.text(), win.act_edit_mode.text())

# 进编辑模式（按钮文字应变"看图模式"，编辑按钮显示）
win.act_edit_mode.setChecked(True)
win._on_toggle_edit_mode(True)
pump(6)
ok("①-5 进编辑模式后按钮变「🖼 看图模式」",
   "看图模式" in win.act_edit_mode.text(), win.act_edit_mode.text())
ok("①-6 编辑类按钮这时才显示出来",
   all(a.isVisible() for a in win._edit_actions),
   f"{sum(1 for a in win._edit_actions if a.isVisible())}/{len(win._edit_actions)}")
ok("①-7 编辑模式 = 矢量（看图模式关着）", mv._view_mode is False)

# ======================================================================
print("===== ② 切到看图模式：烘图 + 藏矢量图元 =====")


def ink():
    """视口里"有东西"的像素占比（背景 #F7F9FB 不算）。

    ★★ 这条是**补漏判据**：v2.7.14 首版漏了"烘完重新取 rect"，结果图烘出来了、
       png 也存了，画面却没切换 —— 而旧判据只看「图元在不在」，
       图元在不在都测不出来，只有数屏幕像素才能抓到。
    """
    im = mv.viewport().grab().toImage()
    bg = QColor("#F7F9FB")
    n = tot = 0
    for y in range(0, im.height(), 4):
        for x in range(0, im.width(), 4):
            c = QColor(im.pixel(x, y))
            tot += 1
            if (abs(c.red() - bg.red()) > 10 or abs(c.green() - bg.green()) > 10
                    or abs(c.blue() - bg.blue()) > 10):
                n += 1
    return n / max(tot, 1)


mv.fit_map()
pump(12)
ink_vector = ink()
print(f"       （编辑模式矢量画面：非背景 {ink_vector * 100:.1f}%）")

# ★★ 必须先**清掉缓存**：只有走"首次烘图"这条路径才会犯那个 bug ——
#    缓存命中时 load_cache 顺手把 rect 也给了，反倒一直是好的。
#    不清缓存 = 永远测不出来（这就是首版探针 30/0 却线上失败的原因）。
for _f in ("_view_image.png", "_view_image_meta.json"):
    _fp = os.path.join(win._data_dir(), _f)
    if os.path.exists(_fp):
        os.remove(_fp)
win._view_img = None
win._view_rect = None

t0 = time.time()
win.act_edit_mode.setChecked(False)
win._on_toggle_edit_mode(False)
cost = time.time() - t0
pump(10)
ok("②-1 已进看图模式", mv._view_mode is True)
ok("②-2 位图图元已铺上", mv._view_item is not None)
if mv._view_item is not None:
    pw, ph = mv._view_item.pix.width(), mv._view_item.pix.height()
    ok("②-3 出的是**超清大图**（5000px 级，不是屏幕缩略图）",
       pw >= 4000 and ph >= 3000, f"{pw}×{ph}，烘图耗时 {cost:.1f}s")
ok("②-4 矢量图元已全部藏起来（这才是「不卡」的关键）",
   len(mv._hidden_items) > 300, f"藏了 {len(mv._hidden_items)} 个")
sid0 = next(iter(mv.station_items))
it0 = mv.station_items[sid0]
ok("②-5 站点图元此刻不可见", it0.isVisible() is False, sid0)
ok("②-6 按钮文字回到「✎ 编辑模式」",
   "编辑模式" in win.act_edit_mode.text(), win.act_edit_mode.text())
pump(12)
ink_view = ink()
ok("②-7 屏幕**真的画出了这张位图**（不是一片空白）",
   ink_view > 0.02, f"非背景 {ink_view * 100:.1f}%")
ok("②-8 画面内容量与矢量时相当（说明位图铺在了正确的位置）",
   abs(ink_view - ink_vector) <= max(ink_vector, 0.02) * 0.6,
   f"看图 {ink_view * 100:.1f}% vs 编辑 {ink_vector * 100:.1f}%")

# ======================================================================
print("===== ③ 看图模式下：能点站点、站名只读、双击不弹编辑框 =====")
win._on_toggle_info_panel()          # 把详情面板放出来
pump(8)
sc = mv.mapFromScene(it0.pos())
QTest.mouseClick(mv.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(sc.x()), int(sc.y())))
pump(15)
ok("③-1 看图模式下点圆点**能选中**", getattr(mv, "_focus_station_id", "") == sid0,
   f"focus={getattr(mv, '_focus_station_id', '')} / 期望 {sid0}")
ok("③-2 详情面板跟着显示这个站",
   win.info_panel.title.text().strip() == sid0, win.info_panel.title.text())
ok("③-3 看图模式下**站名只读**（改了会影响主图上的字）",
   win.info_panel.title.isReadOnly() is True)
blink_seen = set()
for _ in range(8):
    pump(4)
    blink_seen.add(bool(getattr(mv, "_blink_state", False)))
ok("③-4 选中的站**在闪**（红环亮/灭两态都出现过）", len(blink_seen) == 2,
   f"观测到 {sorted(blink_seen)}")

# 双击不许弹编辑框（用计数器抓）
import ui.edit_dialog as _ED  # noqa: E402
calls = {"n": 0}
_orig_init = _ED.EditDialog.__init__


def _spy(self, *a, **k):
    calls["n"] += 1
    return _orig_init(self, *a, **k)


_ED.EditDialog.__init__ = _spy
QTest.mouseDClick(mv.viewport(), Qt.LeftButton, Qt.NoModifier,
                    QPoint(int(sc.x()), int(sc.y())))
pump(10)
ok("③-5 看图模式下双击**不弹编辑框**", calls["n"] == 0, f"弹了 {calls['n']} 次")
_ED.EditDialog.__init__ = _orig_init

# ======================================================================
print("===== ④ png 落盘 + 拖动不白屏 =====")
sec = win._img_settings()
p = IM.png_path(win._data_dir(), sec)
ok("④-1 图片已存成 png 文件", os.path.exists(p), p)
if os.path.exists(p):
    ok("④-2 png 不是空文件", os.path.getsize(p) > 200_000,
       f"{os.path.getsize(p)/1024/1024:.1f} MB")

r = getattr(mv, "_view_rect", None)
ok("④-3 记住了位图的场景范围", r is not None and not r.isEmpty())
if r is not None:
    h = mv.horizontalScrollBar()
    v = mv.verticalScrollBar()
    for _ in range(200):                      # 往右下狠拖
        h.setValue(h.value() - 60)
        v.setValue(v.value() - 60)
    pump(10)
    c = mv.mapToScene(QPoint(mv.viewport().width() // 2, mv.viewport().height() // 2))
    ok("④-4 拖到底也**没跑出图片范围**（不会整屏空白）",
       r.contains(c) or (abs(c.x() - r.center().x()) <= r.width() / 2 + 1 and
                         abs(c.y() - r.center().y()) <= r.height() / 2 + 1),
       f"中心 ({c.x():.0f},{c.y():.0f}) / 图 {r.x():.0f},{r.y():.0f},{r.width():.0f}×{r.height():.0f}")

# ======================================================================
print("===== ⑤ 切回编辑模式：矢量图元全回来 =====")
win.act_edit_mode.setChecked(True)
win._on_toggle_edit_mode(True)
pump(10)
ok("⑤-1 看图模式已退出", mv._view_mode is False)
ok("⑤-2 位图图元已撤掉", mv._view_item is None)
ok("⑤-3 站点图元恢复可见", it0.isVisible() is True, sid0)
ok("⑤-4 站名输入框**恢复可编辑**", win.info_panel.title.isReadOnly() is False)

# ======================================================================
print("===== ⑥ 缓存：数据没变就不重烘（省掉每次开软件等几秒）=====")
_orig_render = IM.render_view_image
cnt = {"n": 0}

# ★ 先清掉缓存，否则"第一次"会直接命中缓存、根本没烘（假通过）
for _f in ("_view_image.png", "_view_image_meta.json"):
    _fp = os.path.join(win._data_dir(), _f)
    if os.path.exists(_fp):
        os.remove(_fp)


def _spy_render(view, px=None):
    cnt["n"] += 1
    return _orig_render(view, IM.PX_PER_UNIT if px is None else px)


IM.render_view_image = _spy_render
win._view_img = None
win._view_rect = None
win._enter_view_mode()
pump(8)
n1 = cnt["n"]
ok("⑥-1 第一次（无缓存）真的烘了", n1 == 1, f"烘了 {n1} 次")
win._view_img = None
win._view_rect = None
win._enter_view_mode()
pump(8)
ok("⑥-2 第二次**走缓存**、不再重烘", cnt["n"] == n1, f"累计 {cnt['n']} 次")
IM.render_view_image = _orig_render

# ======================================================================
print("===== ⑦ 变异自检：关掉「自动生成」后，切看图模式不该出图 =====")
win.act_edit_mode.setChecked(True)
win._on_toggle_edit_mode(True)
pump(6)
d = win._data_dir()
s2 = dict(win._img_settings())
s2["auto_on_enter"] = False
IM.save_settings(d, s2)
mv2_hidden_before = getattr(mv, "_hidden_items", [])
win.act_edit_mode.setChecked(False)
win._on_toggle_edit_mode(False)
pump(8)
ok("⑦-1 关掉自动生成 ⇒ 切过去**不进**看图模式（变异生效）",
   mv._view_mode is False, f"_view_mode={mv._view_mode}")
s2["auto_on_enter"] = True
IM.save_settings(d, s2)
win.act_edit_mode.setChecked(True)
win._on_toggle_edit_mode(True)
pump(6)
win.act_edit_mode.setChecked(False)
win._on_toggle_edit_mode(False)
pump(8)
ok("⑦-2 改回自动生成 ⇒ 又能进看图模式（恢复）", mv._view_mode is True)

print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
if FAILED:
    for n in FAILED:
        print("   FAIL:", n)
