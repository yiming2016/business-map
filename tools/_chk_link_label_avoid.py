# -*- coding: utf-8 -*-
"""
tools/_chk_link_label_avoid.py
==============================
回归：虚线/通道上的"约XX米"**不许叠在一起、不许压站名、不许压站点圆点**（v2.6.22）。

用户原话：
    「你现在和原图好多都没有对照上。按照观看最佳的方式去修改，你自由发挥」

改动前：米数死死钉在两端中点 ⇒ 坪山那一片三条
（坪山高铁站↔坪山 100m / 未来城↔坪山广场 450m / 坪山中心↔坪山中心 450m）
叠成一坨，还压住"站前路东 / 坪山广场"的站名。

本脚本守三件事：
  A 米数之间零重叠（含**变异可抓**：把 LINK_LABEL_AVOID 关掉，必须立刻炸）
  B 米数不压任何**可见站名**、不压任何**站点圆点**
  C 米数一个都不许消失（用户点名要的信息，宁可挤一点也不许没有）

运行：
    C:\\Users\\29773\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe tools/_chk_link_label_avoid.py
"""
from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

# ★ 铁律：测试脚本不许写真数据（MainWindow.close() 里有 dm.save()）
_TMP = Path(tempfile.mkdtemp(prefix="v2622chk_"))
_REAL = CDM.DATA_DIR
for _n in ("stations.json", "lines.json"):
    if (_REAL / _n).exists():
        shutil.copy(_REAL / _n, _TMP / _n)
(_TMP / "covers").mkdir(exist_ok=True)
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtCore import QRectF                     # noqa: E402
from PySide6.QtGui import QFont                       # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

import ui.map_view as MV                              # noqa: E402
from ui.main_window import MainWindow                 # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f"   （{extra}）" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"   （{extra}）" if extra else ""))


def pump(n: int = 14) -> None:
    for _ in range(n):
        QApplication.processEvents()


def set_scale(mv, scale) -> None:
    mv._apply_zoom_transform(scale / max(mv._scale, 1e-9),
                             mv.viewport().rect().center())
    mv._sync_zoom_state()
    mv._apply_station_scale_all()
    mv._apply_line_width()
    pump(8)
    mv._invalidate_nn()
    mv._update_label_visibility()
    pump(10)


def rects_overlap(a: QRectF, b: QRectF, tol: float = 1.0) -> bool:
    inter = a.intersected(b)
    if inter.isEmpty():
        return False
    return inter.width() * inter.height() > tol


def survey(mv):
    """量一遍：米数之间、米数↔站名、米数↔圆点的重叠情况。"""
    links = [it for it in mv.link_items if it.label is not None]
    labels = []
    for it in list(mv.station_items.values()) + list(mv.alt_items.values()):
        if it.is_label_visible():
            labels.append((it.station_id, it.label.sceneBoundingRect()))
    dots = []
    for sid, it in mv.station_items.items():
        r = it.radius()
        p = it.pos()
        dots.append((sid, QRectF(p.x() - r, p.y() - r, r * 2, r * 2)))

    lb = [(it.distance, it._label_scene_rect()) for it in links]
    n_self = sum(1 for i in range(len(lb)) for j in range(i + 1, len(lb))
                 if rects_overlap(lb[i][1], lb[j][1]))
    n_label = sum(1 for _d, r in lb for _s, o in labels if rects_overlap(r, o))
    n_dot = sum(1 for _d, r in lb for _s, o in dots if rects_overlap(r, o))
    return len(lb), n_self, n_label, n_dot, lb


def main() -> int:
    app = QApplication(sys.argv)
    f = QFont("Microsoft YaHei", 10)
    f.setBold(True)
    app.setFont(f)
    win = MainWindow()
    win.resize(1480, 900)
    win.show()
    pump(40)
    mv = win.map_view

    print("\n===== A/B/C 米数摆位（多档缩放）=====")
    # ★ 为什么要扫多档：米数框的**场景**尺寸 = 屏幕字号 / 缩放 ⇒ 缩得越小、
    #   框越大，越容易打架。坪山那三条实测在 0.16~0.40 档叠得最凶，
    #   1.0 档反而各自分得开 —— 只测 1.0 会得到"本来就没事"的假结论。
    SCALES = (0.16, 0.25, 0.40, 1.0)
    res = {}
    for flag in (True, False):
        MV.LINK_LABEL_AVOID = flag
        for s in SCALES:
            set_scale(mv, s)
            res[(flag, s)] = survey(mv)
        print("      避让=%-5s ：" % flag + "  ".join(
            "%.2f→互叠%d/压名%d/压点%d" % (s, res[(flag, s)][1],
                                          res[(flag, s)][2], res[(flag, s)][3])
            for s in SCALES))

    n_on = res[(True, SCALES[0])][0]
    check("米数标签一个都没丢（应为 6 条：4 条 transfer_links + 清湖/坪山中心 2 条 alt_bodies）",
          n_on >= 6, f"实际 {n_on}")
    for s in SCALES:
        n, s_o, l_o, d_o, _lb = res[(True, s)]
        check(f"缩放 {s}：米数之间零重叠", s_o == 0, f"{s_o} 对重叠")
        if s >= 0.40:
            # ★ 判据为什么这档要求"绝对 0"：0.40 是用户默认看图的档位
            #   （状态栏显示 40%），也是"不干净就一眼看得见"的档位。
            check(f"缩放 {s}：米数不压站名、不压圆点", l_o + d_o == 0,
                  f"压名 {l_o} + 压点 {d_o}")
        else:
            # ★ 缩到 0.16/0.25 时，一块米数标签在场景里有 600x80 那么大，
            #   坪山那一小片根本没有"完全空着"的地方 —— 这跟站名排版在最小档
            #   压线率下不去是同一件事（见 _chk_label_on_line 的说明）。
            #   所以这档只要求"比不避让明显好"，不要求绝对 0。
            base = res[(False, s)]
            cut = (base[2] + base[3]) - (l_o + d_o)
            check(f"缩放 {s}：冲突数比『不避让』少 40% 以上",
                  (base[2] + base[3]) > 0 and
                  (l_o + d_o) <= (base[2] + base[3]) * 0.6,
                  f"关 {base[2] + base[3]} → 开 {l_o + d_o}（少 {cut}）")

    # ★ 变异自检：关掉避让 == 回到"死死钉在中点"的老行为，必须能抓到问题，
    #   否则上面那些 0 就是恒真的摆设。
    b40 = res[(False, 0.40)]
    o40 = res[(True, 0.40)]
    check("变异自检：关掉避让后 0.40 档至少 5 处冲突（判据抓得住）",
          b40[2] + b40[3] >= 5, f"关掉时 压名 {b40[2]} + 压点 {b40[3]}")
    check("变异自检：打开避让后 0.40 档冲突清零",
          o40[2] + o40[3] == 0, f"打开时 压名 {o40[2]} + 压点 {o40[3]}")

    print("\n      米数落位一览（缩放 %.2f，打开避让后）：" % SCALES[-1])
    for dist, r in res[(True, SCALES[-1])][4]:
        cx = (r.left() + r.right()) / 2
        cy = (r.top() + r.bottom()) / 2
        print("        %-8s 中心 (%.0f, %.0f)" % (dist or "(无字)", cx, cy))

    MV.LINK_LABEL_AVOID = True
    win.close()
    print(f"\n===== {PASS} 通过 / {FAIL} 失败 =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
