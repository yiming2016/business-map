import sys, time
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt
from ui.map_view import MapView
from core.data_manager import get_data_manager

app = QApplication(sys.argv)
f = QFont("Microsoft YaHei", 10); f.setBold(True); app.setFont(f)
mv = MapView(); mv.resize(1600, 900)
mv.setAttribute(Qt.WA_DontShowOnScreen, True); mv.show()
dm = get_data_manager(); mv.rebuild_lines(); mv.reload_stations(dm.all_stations())
mv.fit_map(); app.processEvents()
h = mv.horizontalScrollBar(); v = mv.verticalScrollBar()

def run(tag):
    for _ in range(8):
        h.setValue(h.value()+20); mv.viewport().repaint()
    t0=time.perf_counter()
    for i in range(80):
        h.setValue(h.minimum()+50+ (i*31) % max(1,h.maximum()-h.minimum()-100))
        v.setValue(v.minimum()+40+ (i*19) % max(1,v.maximum()-v.minimum()-80))
        mv.viewport().repaint()
    dt=time.perf_counter()-t0
    print(f"{tag:<28} {dt/80*1000:>7.2f} ms/帧  ≈{80/dt:>5.0f} FPS")

run("全开")
for it in mv.line_items.values(): it.setVisible(False)
run("隐藏所有线路")
for it in mv.line_items.values(): it.setVisible(True)
for it in mv.station_items.values(): it.setVisible(False)
run("隐藏所有站点")
for it in mv.station_items.values(): it.setVisible(True)
for it in mv.station_items.values(): it.label.setVisible(False)
run("隐藏所有站名文字")
