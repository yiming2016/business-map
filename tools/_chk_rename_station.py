# -*- coding: utf-8 -*-
"""回归：改站名必须**连同所有引用一起改**（v2.6.57 第 ③ 条）。

背景：本工程 `station_id == station_name`，20 条线的站序数组、折点方向表
（elbow_sides.json）、末端号码方块表（terminal_badges.json / badge_offsets.json）、
弧形状表（lines_doc.segment_shapes）、自动描线（lines_doc.traced）、贯通段
（through_links）、换乘连接（transfer_links）、封面图文件名 —— **全都拿站名当键**。

v2.6.57 之前只改 `station_name` 字段不动键 ⇒ 名字显示是新的、内部编号还是旧的
⇒ 半保存：按新名查不到、站序里仍是旧名。

★ 判据只查**落盘后的 JSON 文件**和"界面上还看得到这个站吗"，不复述实现。
★★ elbow_sides.json 实际只覆盖 58 段、**不含罗湖/车公庙这些站** ⇒ 直接拿真表
   断言"键换了"会**假通过**（两边都没有，永远相等）。所以这里在 temp 里
   **人造**几条含该站的记录，让判据真在岗。

用法：
    python tools/_chk_rename_station.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.data_manager as CDM                      # noqa: E402

OLD, NEW = "罗湖", "罗湖改名了"
PY = sys.executable
TAG = "##RENAME##"
# 测试站所在线路（罗湖只属于 1 号线）
HOME_LINES = ["1"]


_SRC_DATA = Path(CDM.DATA_DIR)      # 改名前的真实数据目录（probe 用得到）


def _tmp_dir():
    t = Path(tempfile.mkdtemp(prefix="chkren_"))
    for n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json",
              "elbow_sides.json", "terminal_badges.json"):
        if (_SRC_DATA / n).exists():
            shutil.copy(_SRC_DATA / n, t / n)
    (t / "covers").mkdir(exist_ok=True)
    # ★ 人造：折点方向表（真表里没有罗湖，直接断言会假通过）
    # ★★ elbow_sides.json **不在 INITIAL_FILES 里**，实测源码/用户 data 目录
    #    都**没有**这份文件 ⇒ 无条件 read 会 FileNotFoundError（判据前提消失）。
    #    缺就从空表起步：反正下面要人造记录，判据照样在岗。
    _ep = t / "elbow_sides.json"
    e = json.loads(_ep.read_text(encoding="utf-8")) if _ep.exists() else {}
    e["1|%s|国贸" % OLD] = "b"
    e["1|国贸|%s" % OLD] = "a"
    (t / "elbow_sides.json").write_text(
        json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    # ★ 人造：用户拖动过的方块偏移
    (t / "badge_offsets.json").write_text(
        json.dumps({"1|%s" % OLD: [12.0, -8.0]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return t


_TMP = _tmp_dir()
CDM.STATIONS_FILE = _TMP / "stations.json"
CDM.LINES_FILE = _TMP / "lines.json"
CDM.DATA_DIR = _TMP

from PySide6.QtWidgets import QApplication                          # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from ui.main_window import MainWindow                               # noqa: E402


def pump(n=8):
    for _ in range(n):
        QTest.qWait(10)
        QApplication.processEvents()


def rd(name):
    p = _TMP / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def hit(o, s):
    """递归数"站名"出现了几次（键按 | 分段相等、值字符串全等）"""
    n = 0
    if isinstance(o, dict):
        for k, v in o.items():
            if s in str(k).split("|"):
                n += 1
            n += hit(v, s)
    elif isinstance(o, list):
        for v in o:
            n += (1 if v == s else 0) if isinstance(v, str) else hit(v, s)
    return n


def seq_hits(lines, s):
    return sum(1 for L in lines for x in (L.get("stations") or []) if x == s)


def probe():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    ip = win.info_panel
    ip.show_station(OLD)
    pump(6)
    ip._widgets["station_name"].setText(NEW)
    pump(4)
    ip._on_save()
    pump(8)
    st = rd("stations.json")["stations"]
    win.close()
    print("%s %s" % (TAG, json.dumps({
        "key_new": NEW in st, "key_old": OLD in st,
        "seq_old": seq_hits(rd("lines.json").get("lines") or [], OLD),
    })))
    return 0


def probe_nofile():
    """用户数据目录里**没有** elbow_sides.json（真实环境就是这样 —— 它不在
    `INITIAL_FILES` 里，实测用户 data 目录下不存在）⇒ 改名时必须能从打包内 /
    源码里找到源，改好再**新建**到用户目录。只看 DATA_DIR 就会"读不到 ⇒ 跳过
    ⇒ 改名不同步"。
    """
    t = Path(tempfile.mkdtemp(prefix="chkre_nofile_"))
    for n in ("stations.json", "lines.json", "underlay.png", "trace_cloud.json",
              "terminal_badges.json"):
        if (_SRC_DATA / n).exists():
            shutil.copy(_SRC_DATA / n, t / n)
    (t / "covers").mkdir(exist_ok=True)
    CDM.STATIONS_FILE = t / "stations.json"
    CDM.LINES_FILE = t / "lines.json"
    CDM.DATA_DIR = t
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(10)
    # ★ 用 **肘形表里真实存在的站**（罗湖那份表里没有，改它等于"无记录可改"，
    #   自然不会写文件 —— 那是正确行为，不是 bug，判据换成有记录的站才测得到）。
    # ★★ 真 data 目录里没有 elbow_sides.json（见 _tmp_dir 注释）⇒ 这里自己造
    #    一份放在**候选第二位**（模拟打包内 _MEIPASS 那一份），并把候选函数
    #    临时换掉，让"用户目录没有、别处有 ⇒ 改完新建到用户目录"这条判据真在岗。
    e_src = {"1|%s|国贸" % OLD: "b", "1|国贸|%s" % OLD: "a"}
    _src_dir = Path(tempfile.mkdtemp(prefix="chkre_src_"))
    (_src_dir / "elbow_sides.json").write_text(
        json.dumps(e_src, ensure_ascii=False), encoding="utf-8")
    _orig_cands = CDM.station_keyed_json_candidates
    CDM.station_keyed_json_candidates = (lambda fn: [t / fn, _src_dir / fn])
    cand = None
    for k in e_src:
        for seg in str(k).split("|")[1:]:
            if not cand:
                cand = seg
    OLD_E, NEW_E = cand, cand + "改名了"
    ip = win.info_panel
    ip.show_station(OLD_E)
    pump(6)
    ip._widgets["station_name"].setText(NEW_E)
    pump(4)
    ip._on_save()
    pump(8)
    p = t / "elbow_sides.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        d = None
    created = isinstance(d, dict) and len(d) > 0
    n_new = sum(1 for k in (d or {}) if NEW_E in str(k).split("|"))
    n_old = sum(1 for k in (d or {}) if OLD_E in str(k).split("|"))
    win.close()
    CDM.station_keyed_json_candidates = _orig_cands   # 恢复，别污染后续判据
    print("%s %s" % (TAG, json.dumps({
        "created": created, "n_new": n_new, "n_old": n_old, "who": OLD_E,
    })))
    return 0


def main():
    if "--probe" in sys.argv:
        return probe()
    if "--probe-nofile" in sys.argv:
        return probe_nofile()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(12)
    ip = win.info_panel
    dm = CDM.get_data_manager()
    ok = bad = 0

    def chk(name, cond, detail):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  [OK]   %s\n         %s" % (name, detail))
        else:
            bad += 1
            print("  [FAIL] %s\n         %s" % (name, detail))

    docs = ["stations.json", "lines.json", "elbow_sides.json",
            "terminal_badges.json", "badge_offsets.json"]
    before = {f: rd(f) for f in docs}
    n_before = sum(hit(v, OLD) for v in before.values())
    n_seq_before = seq_hits(before["lines.json"].get("lines") or [], OLD)
    print("改名前：全库出现「%s」%d 次（其中线路站序 %d 次）" % (OLD, n_before, n_seq_before))
    if n_before < 4:
        print("  ！样本太少，判据不可信")

    # ---------- 改名（真实用户路径：面板改字 → 点保存）----------
    ip.show_station(OLD)
    pump(6)
    ip._widgets["station_name"].setText(NEW)
    pump(4)
    ip._on_save()
    pump(10)

    after = {f: rd(f) for f in docs}
    stations = after["stations.json"]["stations"]
    lines = after["lines.json"].get("lines") or []

    chk("A1 stations 的键换成新名、旧名键消失",
        (NEW in stations) and (OLD not in stations),
        "新名键 %s / 旧名键还在 %s" % (NEW in stations, OLD in stations))
    chk("A2 station_id 也跟着换",
        (stations.get(NEW) or {}).get("station_id") == NEW,
        "station_id = %r" % (stations.get(NEW) or {}).get("station_id"))
    chk("A3 线路站序里全换成新名",
        seq_hits(lines, OLD) == 0
        and seq_hits(lines, NEW) == n_seq_before and n_seq_before > 0,
        "站序里旧名 %d 处（应 0）、新名 %d 处（应 %d）"
        % (seq_hits(lines, OLD), seq_hits(lines, NEW), n_seq_before))
    n_old_all = sum(hit(v, OLD) for v in after.values())
    n_new_all = sum(hit(v, NEW) for v in after.values())
    chk("A4 全库：旧名彻底消失、新名数量一致",
        n_old_all == 0 and n_new_all == n_before,
        "旧名 %d 次（应 0）、新名 %d 次（应 %d）" % (n_old_all, n_new_all, n_before))
    eb = after["elbow_sides.json"]
    chk("A5 折点方向表（elbow_sides）跟着换",
        sum(1 for k in eb if OLD in str(k).split("|")) == 0
        and sum(1 for k in eb if NEW in str(k).split("|")) == 2,
        "含新名键 %d 个（应 2）、残留旧名 %d 个（应 0）"
        % (sum(1 for k in eb if NEW in str(k).split("|")),
           sum(1 for k in eb if OLD in str(k).split("|"))))
    tb = after["terminal_badges.json"]
    chk("A6 末端方块表（terminal_badges）跟着换",
        sum(1 for k in tb if OLD in str(k).split("|")) == 0
        and sum(1 for k in tb if NEW in str(k).split("|")) >= 1,
        "含新名键 %d 个、残留旧名 %d 个"
        % (sum(1 for k in tb if NEW in str(k).split("|")),
           sum(1 for k in tb if OLD in str(k).split("|"))))
    off = after["badge_offsets.json"]
    chk("A7 用户拖过的方块偏移（badge_offsets）跟着换",
        ("1|%s" % OLD) not in off and ("1|%s" % NEW) in off,
        "'1|%s' 已消失 = %s，'1|新名' 存在 = %s"
        % (OLD, ("1|%s" % OLD) not in off, ("1|%s" % NEW) in off))

    chk("A8 地图上还能看到这个站（主键换了对得上）",
        NEW in win.map_view.station_items and OLD not in win.map_view.station_items,
        "station_items：新名 %s / 旧名 %s"
        % (NEW in win.map_view.station_items, OLD in win.map_view.station_items))
    in_lines = [str(L.get("id")) for L in dm.all_lines()
                if NEW in (L.get("stations") or [])]
    chk("A9 它仍然挂在原来那几条线上", sorted(in_lines) == sorted(HOME_LINES),
        "现在 %s（原来 %s）" % (in_lines, HOME_LINES))

    # ---------- 改名成已存在的名字 ⇒ 必须拒绝 ----------
    ip.show_station(NEW)
    pump(6)
    ip._widgets["station_name"].setText("老街")
    pump(4)
    ip._on_save()
    pump(8)
    st2 = rd("stations.json")["stations"]
    chk("A10 改成已存在的名字 ⇒ 拒绝、保留原名",
        (st2.get(NEW) or {}).get("station_name") == NEW and "老街" in st2,
        "该站名字仍为 %r，「老街」没被并掉 = %s"
        % ((st2.get(NEW) or {}).get("station_name"), "老街" in st2))

    # ---------- B 变异自检 ----------
    print("-" * 66)
    env = dict(os.environ)
    env["METROEDITOR_NO_RENAME"] = "1"
    r = subprocess.run([PY, str(Path(__file__).resolve()), "--probe"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    m2 = None
    for line in (r.stdout or "").splitlines():
        if TAG in line:
            m2 = json.loads(line.split(TAG, 1)[1].strip())
    if m2 is None:
        chk("B 变异自检（NO_RENAME=1）", False,
            "子进程没给出结论：%s" % ((r.stderr or "")[-300:]))
    else:
        print("  变异（退回只改名字不重键）：新名键 %s、旧名键残留 %s、站序旧名 %d 处"
              % (m2["key_new"], m2["key_old"], m2["seq_old"]))
        chk("B1 变异必须让 A1 失败", not m2["key_new"] or m2["key_old"],
            "变异后新名键 %s、旧名键残留 %s" % (m2["key_new"], m2["key_old"]))
        chk("B2 变异必须让 A3 失败", m2["seq_old"] > 0,
            "变异后站序里旧名 %d 处（>0 才对）" % m2["seq_old"])

    # ---- A11 用户目录里压根没有 elbow_sides.json 的真实场景 ----
    r2 = subprocess.run([PY, str(Path(__file__).resolve()), "--probe-nofile"],
                        capture_output=True, text=True, cwd=str(ROOT))
    m3 = None
    for line in (r2.stdout or "").splitlines():
        if TAG in line:
            m3 = json.loads(line.split(TAG, 1)[1].strip())
    chk("A11 用户目录缺 elbow_sides.json 时，改名也能从打包内找到源并建出一份",
        bool(m3 and m3.get("created") and m3.get("n_new") > 0
             and m3.get("n_old") == 0),
        "子进程结论：%s" % (m3 or (r2.stderr or "")[-200:]))
    print("-" * 66)
    print("通过 %d / 失败 %d" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
