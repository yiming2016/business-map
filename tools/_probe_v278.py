# -*- coding: utf-8 -*-
"""v2.7.8 探针：修「电车/云巴劫持悬浮」（命中改成"圆点优先、字框兜底"）。

用户原话：
  「电车\\云巴的站点，当鼠标划过后，很难悬浮选中正常线路，像是被电车/云巴劫持了」

病根（离屏实测出来的，不是猜的）：
  `station_at()` 取 `scene_.items()` 里**最上面**那个 StationDotItem；而站点 item 的
  boundingRect 里装着**站名文字**（比圆点大十倍的矩形），`scene_.items()` 又是按
  boundingRect 粗筛 ⇒ **谁的字框压住邻居的圆点，鼠标就归谁**。电车/云巴这两条线
  建得最晚 ⇒ 叠在最上层 ⇒ 抢得最凶（383 站里 41 站"站在自己圆点上却命中别人"）。

判据清单：
  T1 每个站**站在自己圆点上** ⇒ station_at 必须命中自己（383/383，错位 0）
  T2 电车/云巴站同样不许被抢（这是用户直接抱怨的那批）
  T3 悬浮不吃 hover 的图元（@alt 副站体）不认领 ⇒ 不会出现"光标变手型但气泡不出"
  T4 点击路径（for_hover=False）行为不变：圆点上照样命中
  T5 站名框中心**仍能**命中自己 ≥ 95%（不能为了防抢把"点字选中"弄丢）
  T6 变异自检：把 station_at 退回"取最上面那个" ⇒ T1 必须变红（判据真在岗）

★ 铁律：探针不许写真数据、不落盘；全程 `QT_QPA_PLATFORM=offscreen`（不开窗口）。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import QPointF                   # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402

app = QApplication(sys.argv)
from ui.main_window import MainWindow                # noqa: E402
import ui.map_view as MV                             # noqa: E402

PASS = []


def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)


win = MainWindow()
mv = win.map_view
TRAM = {"有轨电车", "有轨电车支线", "坪山云巴"}


def lines_of(it):
    return [str(x) for x in (it.data.get("lines") or [])]


def is_tram(it):
    return any(l in TRAM for l in lines_of(it))


def scan(**kw):
    bad = []
    for sid, it in mv.station_items.items():
        got = mv.station_at(QPointF(it.pos()), **kw)
        gid = got.station_id if got is not None else None
        if gid != sid:
            bad.append((sid, lines_of(it), gid))
    return bad


print("\n-- T1 全站：站在自己圆点上必须命中自己 --")
bad = scan(for_hover=True)
ok("T1a 圆点命中错位 = 0", len(bad) == 0, f"错位 {len(bad)} / {len(mv.station_items)}")
for sid, ls, gid in bad[:8]:
    print(f"      {sid} 线={ls} ← 命中了 {gid}")

print("\n-- T2 电车/云巴站不许被抢 --")
tram_bad = [b for b in bad if any(l in TRAM for l in b[1])]
ok("T2 电车/云巴站命中错位 = 0", len(tram_bad) == 0, f"{len(tram_bad)} 个")
n_tram = sum(1 for it in mv.station_items.values() if is_tram(it))
print(f"      （电车/云巴站共 {n_tram} 个）")

print("\n-- T3 @alt 副站体（不吃 hover）不许认领悬浮 --")
alts = list(getattr(mv, "alt_items", {}).values())
hij = [a for a in alts
       if (mv.station_at(QPointF(a.pos()), for_hover=True) or None) is a]
ok("T3a 悬浮不认领不吃 hover 的副站体", len(hij) == 0, f"{len(hij)} / {len(alts)}")
ok("T3b 副站体确实把 hover 关掉了",
   all(not a.acceptHoverEvents() for a in alts) if alts else True,
   f"{len(alts)} 个副站体")

print("\n-- T4 点击路径（for_hover=False）仍是老行为 --")
bad_click = scan()
ok("T4 点击时圆点照样命中自己", len(bad_click) == 0, f"错位 {len(bad_click)}")

print("\n-- T5 站名框中心仍能命中自己 --")
lab_miss = []
for sid, it in mv.station_items.items():
    try:
        r = it.label_scene_rect()
    except Exception:
        continue
    if r.width() <= 0 or r.height() <= 0:
        continue
    got = mv.station_at(QPointF(r.center()), for_hover=True)
    if got is None or got.station_id != sid:
        lab_miss.append((sid, got.station_id if got else None))
rate = 1.0 - len(lab_miss) / max(1, len(mv.station_items))
ok("T5 站名框中心命中率 ≥ 95%", rate >= 0.95,
   f"{rate * 100:.1f}%（丢 {len(lab_miss)}：{lab_miss[:6]}）")

print("\n-- T6 变异自检：退回旧实现（取最上面那个）⇒ T1 必须变红 --")
_old = MV.MapView.station_at


def old_station_at(self, scene_pos, for_hover=False):
    for it in self.scene_.items(scene_pos):
        if isinstance(it, MV.StationDotItem):
            return it
        p = it.parentItem()
        while p is not None:
            if isinstance(p, MV.StationDotItem):
                return p
            p = p.parentItem()
    return None


MV.MapView.station_at = old_station_at
try:
    bad_old = scan(for_hover=True)
finally:
    MV.MapView.station_at = _old
ok("T6 旧实现确实会错位 ⇒ 判据在岗", len(bad_old) >= 20,
   f"旧实现错位 {len(bad_old)} 个（新实现 {len(bad)} 个）")

n_fail = len(PASS) - sum(PASS)
print(f"\n===== 结果：{sum(PASS)} 通过 / {n_fail} 失败 =====")
win.close()
sys.exit(1 if n_fail else 0)
