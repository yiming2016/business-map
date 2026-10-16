"""把程序里所有可能耗时的操作挨个计时，找出能撑到『未响应』级别的那个。"""
from __future__ import annotations
import sys, time
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from core.data_manager import get_data_manager
from ui.main_window import MainWindow

def pump(ms=200):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)

def bench(label, fn, n=3):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        app.processEvents()
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    med = ts[len(ts) // 2]
    flag = "🔴🔴 致命" if med > 3000 else ("🔴 很慢" if med > 1000
           else ("🟡 偏慢" if med > 200 else "  ok  "))
    print(f"  {flag} {label:<42} 中位 {med:8.1f} ms   次数={n}  样本={[round(x) for x in ts]}",
          flush=True)
    return med

win = MainWindow(); win.resize(1480, 900); win.show(); pump(800)
mv = win.map_view
dm = get_data_manager()
sids = list(dm.all_stations().keys())
sid = sids[0]
print(f"站点数 = {len(sids)}，线路数 = {len(dm.all_lines())}")
print()

print("=" * 100)
print("A) 地图侧的重活")
print("=" * 100)
bench("_update_label_visibility()  站名防重叠排版", mv._update_label_visibility, 3)
bench("_compute_nn()  最近邻（O(N²)）", mv._compute_nn, 3)
bench("rebuild_lines()  重建所有线路", mv.rebuild_lines, 3)
bench("reload_stations(379)  全量重建站点图元", lambda: mv.reload_stations(dm.all_stations()), 2)
bench("_apply_station_scale_all()  缩放收尾", mv._apply_station_scale_all, 3)
bench("_update_label_visibility 强制重算",
      lambda: (mv._invalidate_nn(), mv._update_label_visibility()), 3)

print()
print("=" * 100)
print("B) 数据侧")
print("=" * 100)
bench("dm.save()  写盘", dm.save, 3)
bench("dm.all_stations()", dm.all_stations, 3)
st = dm.get_station(sid)
bench("dm.resolve_cover(data)  悬浮提示每次鼠标移动都调", lambda: dm.resolve_cover(st), 5)

print()
print("=" * 100)
print("C) 校验一段：把整站名字都改掉再收尾（模拟改名后的重排）")
print("=" * 100)
def rename_all():
    for i, s in enumerate(sids):
        it = mv.station_items.get(s)
        if it:
            it.data["station_name"] = f"测试站{i}"
            it.invalidate_sprite()
    mv._invalidate_nn()
    mv._update_label_visibility()
    for it in mv.station_items.values():
        it.render_sprite(mv.devicePixelRatioF())
bench("改名 379 站 + 重排 + 全量重建 sprite", rename_all, 1)

print()
print("=" * 100)
print("D) 面板/弹窗重建")
print("=" * 100)
bench("info_panel.show_station()  重建右侧表单",
      lambda: win.info_panel.show_station(sid), 3)
from ui.edit_dialog import EditDialog
def mk_dlg():
    d = EditDialog(station_id=sid, parent=win)
    d.show()
    d._collect()
    d.close()
bench("EditDialog 构造+显示+取值", mk_dlg, 3)

win.close()
print("[DONE]")
