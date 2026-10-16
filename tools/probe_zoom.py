"""缩放全程逐帧计时探针：定位"顿挫"的确切来源。

模拟 3 轮滚轮手势（连续 10 格 × 3 轮，间隔 500ms），记录：
  - begin_snap：手势开始时 viewport().grab() 抓快照的耗时（预期嫌疑①：每轮手势起点一次全场景重绘）
  - step：每帧步进耗时（16ms 预算）
  - upd：每帧快照拉伸 blit 耗时
  - FINAL：停手后全量尺寸+排版收尾耗时（预期嫌疑②：每轮手势终点一次大冻结）
  - 实际帧间隔抖动（预期嫌疑③：CoarseTimer 在 Windows 上 16→31ms 抖动）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QPointF, QPoint
from PySide6.QtGui import QWheelEvent

app = QApplication(sys.argv)

# ★ Windows 计时器粒度：默认 15.6ms 会让 16ms 动画定时器抖到 15.6~31ms。
#   timeBeginPeriod(1) 提到 1ms 粒度 —— 真机顿挫的头号嫌疑
import ctypes
if sys.platform == "win32":
    ctypes.windll.winmm.timeBeginPeriod(1)

from core.data_manager import get_data_manager
from ui.map_view import MapView

dm = get_data_manager()
v = MapView()
v.resize(1400, 900)
v.rebuild_lines()
v.reload_stations(dm.all_stations())
v.show()
app.processEvents()

t0 = time.perf_counter()
marks = []          # (t_ms, text)
last_t = [t0]


def mark(text):
    now = time.perf_counter()
    marks.append((1000 * (now - t0), 1000 * (now - last_t[0]), text))
    last_t[0] = now


def wrap(obj, name, label):
    orig = getattr(obj, name)

    def wrapper(*a, **kw):
        s = time.perf_counter()
        r = orig(*a, **kw)
        mark(f"{label} {1000 * (time.perf_counter() - s):.1f}ms")
        return r

    setattr(obj, name, wrapper)


wrap(v, "_begin_zoom_snap", "begin_snap")
wrap(v, "_zoom_step", "step")
wrap(v, "_update_snap_pixmap", "  upd")
wrap(v, "_apply_station_scale_all", "FINAL")
wrap(v, "_end_zoom_snap", "end_snap")


# paint 事件探针：viewport / 快照 QLabel 每次重绘的耗时（嫌疑最大但之前未测量）
from PySide6.QtCore import QEvent, QObject


class PaintProbe(QObject):
    def __init__(self, label):
        super().__init__()
        self.label = label
        # mode: 'observe' 只记录不拦截（真实路径）；'intercept' 拦截绕过正常派发
        self.mode = os.environ.get("PROBE_PAINT_MODE", "observe")

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Paint:
            return False
        name = "snap_label" if obj is self.label else "viewport"
        if self.mode == "intercept":
            s = time.perf_counter()
            obj.__class__.event(obj, ev)
            mark(f"    paint({name}) {1000 * (time.perf_counter() - s):.1f}ms")
            return True
        # observe：记录脏区大小与位置，然后放行（不改行为）
        r = ev.rect()
        mark(f"    paint({name}) rect=({r.x()},{r.y()},{r.width()}x{r.height()})")
        return False

    def post_log(self):
        """observe 模式：paint 结束时间由下一个事件近似，不精确；仅记录脏区。"""
        pass


pp = PaintProbe(v._snap_label)
v.viewport().installEventFilter(pp)
v._snap_label.installEventFilter(pp)

# 收尾/动画定时器 instrumentation
_fin_start_orig = v._zoom_finish.start


def fin_start(*a):
    mark(f"    finish.start() ({v._zoom_finish.interval()}ms single-shot)")
    return _fin_start_orig(*a)


v._zoom_finish.start = fin_start
v._zoom_finish.timeout.connect(lambda: mark("    finish FIRED -> finalize"))
_anim_stop_orig = v._zoom_anim.stop


def anim_stop(*a):
    mark("    anim.stop()")
    return _anim_stop_orig(*a)


v._zoom_anim.stop = anim_stop


def wheel(delta):
    pos = QPointF(v.viewport().rect().center())
    e = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, delta),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(v.viewport(), e)


# 3 轮手势：每轮 10 格 × 间隔 40ms，轮间 500ms
schedule = []
for burst in range(3):
    for i in range(10):
        schedule.append((burst * 540 + i * 40, 120))

idx = [0]


def tick():
    now = 1000 * (time.perf_counter() - t0)
    sent = False
    while idx[0] < len(schedule) and schedule[idx[0]][0] <= now:
        d = schedule[idx[0]][1]
        idx[0] += 1
        wheel(d)
        sent = True
    if sent:
        if idx[0] == 10:
            mark("── 手势1结束(10格)")
        elif idx[0] == 20:
            mark("── 手势2结束")
        elif idx[0] == 30:
            mark("── 手势3结束")


timer = QTimer()
timer.setInterval(10)
timer.timeout.connect(tick)
timer.start()

# ★ 用标准事件循环（exec）跑：与真实应用一致。
#   旧版探针用 processEvents()+sleep 忙等 —— Windows 上 sleep 粒度 15.6ms 且
#   不阻塞的 processEvents 不等待定时器到期，测出 70~120ms 假帧距（方法论缺陷）。
QTimer.singleShot(3000, app.quit)
app.exec()

# 最后真实重绘一次
s = time.perf_counter()
v.viewport().update()
app.processEvents()
mark(f"rest_repaint {1000 * (time.perf_counter() - s):.1f}ms")

# 退出前状态快照
print(f"\n== 退出时状态: finish_active={v._zoom_finish.isActive()} "
      f"anim_active={v._zoom_anim.isActive()} snap_active={v._zoom_snap is not None} "
      f"_scale={v._scale:.4f} transform={v.transform().m11():.4f}")

# 统计帧距分布
step_ts = [t for t, _, txt in marks if txt.startswith("step")]
gaps = [b - a for a, b in zip(step_ts, step_ts[1:])]
if gaps:
    gaps.sort()
    print(f"\n== 帧距统计: 中位 {gaps[len(gaps)//2]:.1f}ms  P90 {gaps[int(len(gaps)*0.9)]:.1f}ms  最大 {gaps[-1]:.1f}ms  (目标 16ms)")
print()

prev = 0.0
for t, dt, text in marks:
    print(f"t={t:7.1f}ms  距上个事件 {dt:5.1f}ms  {text}")
