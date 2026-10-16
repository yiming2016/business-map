"""
tools/_probe_v290.py —— v2.6.90 三件事的探针
T1 搜索框宽度 112（160 的 70%）
T2 悬浮气泡三段式「站名 3号线 福田区」同行垂直居中
T3 定位闪烁（光晕 + 文字透明度抖动，收尾复原）
T4 点站点展开详情面板 / 左键点空白收起
"""
import os
import sys

os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui.main_window import MainWindow
from ui.tooltip import HoverTip

PASS = []

def ok(name, cond, extra=""):
    PASS.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)

w = MainWindow()
w.resize(1480, 900)
w.show()
app.processEvents()

# ---------- T1 搜索框宽度 ----------
wd = w.search_box.width()
ok("T1 搜索框宽度=112", wd == 112, f"width={wd}")

# ---------- T2 气泡三段式 ----------
tip = w.tip
data = {"station_name": "福保", "lines": ["3"], "district": "福田区"}
tip.show_for(QPoint(200, 200), data)
app.processEvents()
ok("T2a 站名", tip.lbl_title.text() == "福保", tip.lbl_title.text())
ok("T2b 线路=3号线", tip.lbl_lines.text() == "3号线", tip.lbl_lines.text())
ok("T2c 区=福田区可见", tip.lbl_district.text() == "福田区" and not tip.lbl_district.isHidden())
# 同一行 + 垂直中心对齐
r1, r2, r3 = (tip.lbl_title.geometry(), tip.lbl_lines.geometry(),
              tip.lbl_district.geometry())
same_row = abs(r1.center().y() - r2.center().y()) <= 2 and abs(r2.center().y() - r3.center().y()) <= 2
ok("T2d 三段同行垂直居中", same_row, f"{r1.center().y()},{r2.center().y()},{r3.center().y()}")
ok("T2e 顺序 站名<线路<区", r1.right() <= r2.left() and r2.right() <= r3.left())
# 多线换乘格式
tip.show_for(QPoint(200, 200), {"station_name": "车公庙", "lines": ["1", "7", "9", "11"], "district": "福田区"})
app.processEvents()
ok("T2f 多线=1号线、7号线…", tip.lbl_lines.text() == "1号线、7号线、9号线、11号线", tip.lbl_lines.text())
# 无区隐藏
tip.show_for(QPoint(200, 200), {"station_name": "某站", "lines": ["5"], "district": ""})
app.processEvents()
ok("T2g 无区时隐藏", tip.lbl_district.isHidden())

# ---------- T3 定位闪烁 ----------
sid = next(iter(w.map_view.station_items))
item = w.map_view.station_items[sid]
w.map_view.blink_station(sid)
ok("T3a 定时器已启动", w.map_view._blink_timer is not None and w.map_view._blink_timer.isActive())
w.map_view._tick_blink()
ok("T3b 亮: _blink=True 光晕", item._blink is True)
w.map_view._tick_blink()
ok("T3c 灭: _blink=False 字复原", item._blink is False and item.label.opacity() == 1.0)
w.map_view._tick_blink()
ok("T3d 再亮: 字透明度 0.15", item._blink is True and item.label.opacity() == 0.15)
w.map_view._stop_blink()
ok("T3e 停止后字不透明度复原", item._blink is False and item.label.opacity() == 1.0
   and w.map_view._blink_timer is None)

# ---------- T4 点站展开 / 点空白收起 ----------
w.btn_info_toggle.click()            # 先手动收起
app.processEvents()
ok("T4a 预置:面板已收起", w.info_panel.isHidden())
w.map_view.select_station(sid)       # 单击站点路径 = select_station(emit=True)
app.processEvents()
ok("T4b 点站点⇒面板展开", not w.info_panel.isHidden())
w.map_view.map_empty_clicked.emit()  # 左键点空白收起（信号已接）
app.processEvents()
ok("T4c 点空白⇒面板收起", w.info_panel.isHidden())
# 中键不触发的保证在 map_view.mouseReleaseEvent（btn==LeftButton 判定），探针旁证信号只连了一个
w.map_view.select_station(sid)
app.processEvents()
ok("T4d 再点站⇒又展开", not w.info_panel.isHidden())
w.btn_info_toggle.click()            # 还原
app.processEvents()

tip.hide()
w.close()
app.processEvents()
print(f"TOTAL {sum(PASS)}/{len(PASS)}")
sys.exit(0 if all(PASS) else 1)
