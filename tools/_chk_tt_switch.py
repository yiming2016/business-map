# -*- coding: utf-8 -*-
"""v2.6.10 回归：切换「日期类型」下拉 → 表格数据必须跟着变。

★ 起因：v2.6.9 用户报「下拉菜单可以选择了，但对应的首末班车数据没改变」。
  实测切换**是生效的**（`_probe_v269_switch*.py` / `_probe_v269_combo_repaint.py`），
  真因是官方数据三档差别极小（346 站里 86 站「工作日 vs 休息日」零差异）。
  ⇒ 修法两条：① 信号双保险（`activated` + `currentIndexChanged`）；
             ② 加一行**差异提示**，让"数据一样"这件事一眼可见。

判据（每条都配一个"天真变体"验证它真能报警）：
  A 三档不同：切档后可见分组 / 屏上文本 / 差异提示三者都对
  B 三档全同：提示必须明确说"完全相同"
  C `activated` 单独触发（= 用户从列表里点了一项）也能切
  D ★★ 切档**绝不许改数据**：`text()` 前后逐字节相同
  E 只有一档时：下拉与提示都隐藏
  F 重建（set_text）后不闪退、提示仍可用
  G str 实参也能归一化（防信号重载踩坑）
"""
from __future__ import annotations

import os, sys, shutil, tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

# ★ 测试不许写真数据：拷一份到临时目录再指过去（MEMORY §5.10）
_TMP = tempfile.mkdtemp(prefix="chk_tt_switch_")
import core.data_manager as CDM                                     # noqa: E402
for _f in ("stations.json", "lines.json"):
    _src = Path(CDM.DATA_DIR) / _f
    if Path(_src).exists():
        shutil.copy(_src, os.path.join(_TMP, _f))
CDM.DATA_DIR = _TMP
CDM.STATIONS_FILE = os.path.join(_TMP, "stations.json")
CDM.LINES_FILE = os.path.join(_TMP, "lines.json")

from PySide6.QtWidgets import QApplication, QLineEdit, QWidget, QVBoxLayout  # noqa: E402
import PySide6.QtWidgets as QtW                                     # noqa: E402
QtW.QMessageBox.warning = staticmethod(lambda *a, **k: None)

from ui.timetable_editor import TimetableEditor                       # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

fails = []


def check(cond, msg):
    print(("  [OK]  " if cond else "  [!!]  ") + msg)
    if not cond:
        fails.append(msg)


DIFF3 = "\n".join([
    "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21",
    "休息日 · 1号线：往罗湖 首06:20 末23:47；往机场东 首06:55 末23:21",
    # 节假日：首班 2 个 + 末班 2 个都变 ⇒ 期望 4（与休息日的 2 区分开，
    # 这样"提示写死一个数"的变体一定会被抓）
    "节假日 · 1号线：往罗湖 首06:35 末00:47；往机场东 首07:10 末00:21",
])
SAME3 = "\n".join([
    "工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21",
    "休息日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21",
    "节假日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21",
])
ONE = "工作日 · 1号线：往罗湖 首06:02 末23:47"


_KEEP: list = []      # ★ 宿主窗口必须**活着**：函数一返回局部变量就没引用了，
                       #   QWidget 被销毁会把里面的编辑器一起带走（实测报
                       #   "Internal C++ object (_DateCombo) already deleted"）。


def mount(ed: TimetableEditor) -> QWidget:
    win = QWidget()
    v = QVBoxLayout(win)
    v.addWidget(ed)
    win.resize(900, 520)
    win.show()
    app.processEvents()
    app.processEvents()
    _KEEP.append(win)
    return win


def visible_texts(ed):
    """当前**屏上**能读到的文本（只数可见分组里的输入框）。"""
    out = []
    for i, b in enumerate(ed._group_boxes):
        if b.isVisible():
            out.append((i, [w.text() for w in b.findChildren(QLineEdit)]))
    return out


def tip(ed):
    lab = getattr(ed, "_diff_label", None)
    return None if lab is None else (lab.text(), lab.isVisible())


print("=" * 72)
print("A 组：三档各不相同")
print("=" * 72)
ed = TimetableEditor(DIFF3)
mount(ed)
cb = ed.date_combo
check(cb.count() == 3, f"下拉 3 项：{[cb.itemText(i) for i in range(cb.count())]}")
expect = [
    ["1号线", "往罗湖", "06:02", "23:47", "往机场东", "06:41", "23:21"],
    ["1号线", "往罗湖", "06:20", "23:47", "往机场东", "06:55", "23:21"],
    ["1号线", "往罗湖", "06:35", "00:47", "往机场东", "07:10", "00:21"],
]
for idx in range(3):
    cb.setCurrentIndex(idx)
    app.processEvents()
    vis = visible_texts(ed)
    check(len(vis) == 1 and vis[0][0] == idx,
          f"切到 {idx}：只显示第 {idx} 组（实际 {[v[0] for v in vis]}）")
    check(vis[0][1] == expect[idx],
          f"切到 {idx}：屏上文本 = {vis[0][1]}")
    t = tip(ed)
    if idx == 0:
        check(t is None or not t[1], f"基准档不显示提示（{t}）")
    else:
        want = ("与「工作日」相比：2 个时刻不同" if idx == 1
                else "与「工作日」相比：4 个时刻不同")
        check(t is not None and t[1] and t[0] == want,
              f"切到 {idx}：提示 = {t!r}（期望 {want!r}）")

print()
print("=" * 72)
print("B 组：三档完全相同（= 用户报的那类站）")
print("=" * 72)
ed2 = TimetableEditor(SAME3)
mount(ed2)
cb2 = ed2.date_combo
cb2.setCurrentIndex(1)
app.processEvents()
t = tip(ed2)
check(t is not None and t[1] and "完全相同" in t[0],
      f"提示必须明说完全相同：{t!r}")
vis = visible_texts(ed2)
check(len(vis) == 1 and vis[0][0] == 1, f"仍然切到了第 1 组：{[v[0] for v in vis]}")

print()
print("=" * 72)
print("C 组：activated（用户从列表里点了一项）也要能切")
print("=" * 72)
cb2.setCurrentIndex(0)
app.processEvents()
cb2.activated[int].emit(2)
app.processEvents()
vis = visible_texts(ed2)
check(ed2._cur == 2 and len(vis) == 1 and vis[0][0] == 2,
      f"activated(2) 后 _cur={ed2._cur} 可见={[v[0] for v in vis]}")

print()
print("=" * 72)
print("D 组：★ 切档绝不许改数据（text() 前后逐字节相同）")
print("=" * 72)
before = ed.text()
for idx in (1, 2, 0, 2):
    ed.date_combo.setCurrentIndex(idx)
    app.processEvents()
check(ed.text() == before, f"切 4 次后 text() 不变（{before[:40]}…）")

print()
print("=" * 72)
print("E 组：只有一档 ⇒ 下拉与提示都隐藏")
print("=" * 72)
ed3 = TimetableEditor(ONE)
mount(ed3)
check(not ed3.date_combo.isVisible(), "下拉隐藏")
t3 = tip(ed3)
check(t3 is None or not t3[1], f"提示隐藏（{t3}）")

print()
print("=" * 72)
print("F 组：重建后不闪退、提示仍可用")
print("=" * 72)
ed.set_text(DIFF3)
app.processEvents()
cb = ed.date_combo
cb.setCurrentIndex(2)
app.processEvents()
t = tip(ed)
check(t is not None and t[1] and "4 个时刻不同" in t[0], f"重建后提示正常：{t!r}")
vis = visible_texts(ed)
check(len(vis) == 1 and vis[0][0] == 2, "重建后仍能切档")

print()
print("=" * 72)
print("G 组：str 实参也能归一化（防信号重载踩坑）")
print("=" * 72)
ed2._on_date_changed("工作日")
app.processEvents()
check(ed2._cur == 0, f"传字符串 '工作日' ⇒ _cur={ed2._cur}（期望 0）")
ed2._on_date_changed("节假日")
app.processEvents()
check(ed2._cur == 2, f"传字符串 '节假日' ⇒ _cur={ed2._cur}（期望 2）")

# ============================================================ 变异测试
print()
print("=" * 72)
print("变异测试：每条判据都要能真报警")
print("=" * 72)


class _Dead(TimetableEditor):
    """变体 1：槽函数空操作（= 切档不生效）"""

    def _on_date_changed(self, *a):
        pass


d = _Dead(DIFF3)
mount(d)
d.date_combo.setCurrentIndex(1)
app.processEvents()
vis = visible_texts(d)
check(not (len(vis) == 1 and vis[0][0] == 1),
      f"[变异1] 空槽 ⇒ A 组必须报警（实际可见 {[v[0] for v in vis]}）")


class _NoActivated(TimetableEditor):
    """变体 2：只接 currentIndexChanged，不接 activated"""

    def _new_combo(self):
        cb = super()._new_combo()
        try:
            cb.activated[int].disconnect(self._on_date_changed)
        except Exception:
            pass
        return cb


n = _NoActivated(DIFF3)
mount(n)
n.date_combo.activated[int].emit(2)
app.processEvents()
check(n._cur != 2,
      f"[变异2] 不接 activated ⇒ C 组必须报警（实际 _cur={n._cur}）")


class _FakeTip(TimetableEditor):
    """变体 3：提示永远写"完全相同"（差异计数是假的）"""

    def _sync_diff_label(self):
        lab = getattr(self, "_diff_label", None)
        if lab is not None:
            lab.setText("与「工作日」完全相同")
            lab.show()


fk = _FakeTip(DIFF3)
mount(fk)
fk.date_combo.setCurrentIndex(1)
app.processEvents()
t = tip(fk)
check(not (t and "个时刻不同" in t[0]),
      f"[变异3] 假提示 ⇒ A 组必须报警（实际 {t!r}）")


class _NoNorm(TimetableEditor):
    """变体 4：不做归一化（str 实参会当 0 处理）"""

    def _norm_idx(self, v):
        return 0


nn = _NoNorm(DIFF3)
mount(nn)
nn._on_date_changed("节假日")
app.processEvents()
check(nn._cur != 2, f"[变异4] 不归一化 ⇒ G 组必须报警（实际 _cur={nn._cur}）")

print()
print("=" * 72)
print("结果：%d 项失败" % len(fails))
for f in fails:
    print("   ✗", f)
print("=" * 72)
sys.exit(1 if fails else 0)
