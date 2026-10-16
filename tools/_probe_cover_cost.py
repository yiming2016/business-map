"""
量化 `_refresh_cover_button()` 的开销，以及它在一次「窗口重排」里被调用多少次。
关键：它每次都重新读盘 + 解码 + SmoothTransformation 缩放封面图。
"""
from __future__ import annotations
import sys, time, shutil
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from core.data_manager import get_data_manager
from ui.edit_dialog import EditDialog
from ui.widgets import rounded_pixmap

def pump(ms=150):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)

# ---- 计数 ----
CALLS = {"n": 0}
_orig = EditDialog._refresh_cover_button
def counted(self):
    CALLS["n"] += 1
    return _orig(self)
EditDialog._refresh_cover_button = counted

dm = get_data_manager()
allst = dm.all_stations()
with_cover = [sid for sid, d in allst.items() if dm.resolve_cover(d)]
print(f"379 站点里带封面图的 = {len(with_cover)}")

# 造一张"手机照片"级的大图，看最坏情况
big = SRC / "logs" / "_big_cover.jpg"
pix = QPixmap(4032, 3024)
pix.fill()
pix.save(str(big), "JPEG", 85)
print(f"测试用大图 = {pix.width()}x{pix.height()} （12.2MP）  {big.stat().st_size/1024/1024:.1f} MB")

print()
print("=" * 100)
print("① 单次 rounded_pixmap 的耗时（这就是 _refresh_cover_button 的核心开销）")
print("=" * 100)
for tag, path, size in [
    ("640x640 小图 → 230px",  SRC.parent / "软件" / "data" / "covers" / "左炮台东.jpg", 230),
    ("4032x3024 大图 → 230px", big, 230),
    ("4032x3024 大图 → 174px", big, 174),
]:
    if not Path(path).exists():
        print(f"  (跳过 {tag}：文件不存在)")
        continue
    ts = []
    for _ in range(3):
        t0 = time.perf_counter()
        pm = rounded_pixmap(path, size, size, radius=int(size * 0.2))
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    flag = "🔴 很慢" if ts[1] > 100 else ("🟡" if ts[1] > 30 else "  ok")
    print(f"  {flag} {tag:<28} 中位 {ts[1]:8.1f} ms  样本 {[round(x) for x in ts]}")

print()
print("=" * 100)
print("② 打开一个带封面图的站点弹窗，看 _refresh_cover_button 被调用多少次")
print("=" * 100)
if with_cover:
    sid = with_cover[0]
else:
    sid = list(allst.keys())[0]
    dm.upsert_station(sid, {"cover": "左炮台台.jpg"})
print(f"  测试站点 = {sid}  cover = {allst[sid].get('cover')!r}")

CALLS["n"] = 0
dlg = EditDialog(station_id=sid, parent=None)
dlg.show()
pump(800)
n_show = CALLS["n"]
print(f"  弹窗 show() 稳定后，_refresh_cover_button 被调用 {n_show} 次")

CALLS["n"] = 0
t0 = time.perf_counter()
for w in (700, 720, 740, 760):
    dlg.resize(w, 680)
    pump(120)
dt = (time.perf_counter() - t0) * 1000.0
print(f"  连续改 4 次窗口大小 → 被调用 {CALLS['n']} 次，共 {dt:.0f} ms")

CALLS["n"] = 0
t0 = time.perf_counter()
for h in (700, 720, 740, 760):
    dlg.resize(600, h)
    pump(120)
dt = (time.perf_counter() - t0) * 1000.0
print(f"  连续改 4 次窗口高度 → 被调用 {CALLS['n']} 次，共 {dt:.0f} ms")

print()
print("=" * 100)
print("③ 把封面换成 12MP 大图后，重复②")
print("=" * 100)
# 直接把 cover_btn 的图标源指到大图，模拟用户选了手机照片
dlg._cover_src = str(big)
CALLS["n"] = 0
t0 = time.perf_counter()
dlg._refresh_cover_button()
dt = (time.perf_counter() - t0) * 1000.0
print(f"  单次 _refresh_cover_button（12MP 图） = {dt:.1f} ms")

CALLS["n"] = 0
t0 = time.perf_counter()
for w in (700, 720, 740, 760, 700, 720, 740, 760):
    dlg.resize(w, 680)
    pump(140)
dt = (time.perf_counter() - t0) * 1000.0
print(f"  连续改 8 次窗口大小（12MP 图）→ 调用 {CALLS['n']} 次，共 {dt:.0f} ms")
print(f"     ⚠️ 每次窗口变化平均要花 {dt/max(1,CALLS['n']):.0f} ms 在重读封面图上")

dlg.close()
try:
    big.unlink()
except Exception:
    pass
print("[DONE]")
