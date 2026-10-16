# -*- coding: utf-8 -*-
"""
import_szmc_official.py —— 把**深圳地铁官网**抓来的官方数据导入软件。

配套：`tools/fetch_szmc_official.py` 抓回来放在 `源码/_data_szmc/raw/<编号>.json`。

写哪些字段（用户 2026-09-24 定的）：
    exits          出入口信息        ← 官网 outAndText
    timetable      首末班车（新增字段）← 官网 workDay / dayoff / holidays
    bus_transfer   公交换乘（新增字段）← 官网 busInof

★★★ 三条硬规矩（跟 import_ai_reply.py 一脉相承，都是踩出来的）
  1. **导入前必须先关掉正在运行的 exe**。软件内存里还装着旧数据，
     只要它随手保存一次，就把你刚导入的结果**覆盖回旧的**。
  2. **导入前备份，任一条断言不对就自动回滚**。
  3. **只填"空的"，已有内容一个字都不许改**（用户明说的）。
     所以：目标字段非空就跳过；简介/地标/备注/设施必须导入前后**完全相同**；
     坐标 x/y / lines / is_transfer / station_name 不许动；lines.json 字节不许变。

用法：
    python tools/import_szmc_official.py                # 【默认】先在临时副本上演练，报告
    python tools/import_szmc_official.py --samples 3    # 看 3 个站的成品长什么样
    python tools/import_szmc_official.py --apply        # 真导入（会先要求关掉 exe）
    python tools/import_szmc_official.py --apply --force  # 检测不到进程也强行导（慎用）
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT.parent / "软件" / "data"
DEFAULT_SRC = ROOT / "_data_szmc"

# 本工具要写的字段
TARGETS = ["exits", "timetable", "bus_transfer"]
# 这些一个字都不许动
FROZEN = ["x", "y", "lines", "is_transfer", "open_date", "station_name"]
# 已有文案：导入前后必须完全相同（验证"没顺手改到别处"）
TEXT_KEEP = ["description", "landmarks", "notes", "facilities"]

SCHEDULE = [("workDay", "工作日"), ("dayoff", "休息日"), ("holidays", "节假日")]


# ---------------------------------------------------------------- 守卫
def exe_is_running() -> bool:
    """★ 查不到时按【还在跑】处理（保守）：宁可让用户加 --force。"""
    tried = 0
    for cmd in (
        ["tasklist"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Name SZ_MetroEditor -ErrorAction SilentlyContinue)"
         " | Out-String"],
    ):
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=25)
            raw = p.stdout
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            tried += 1
            if "SZ_MetroEditor" in (raw or ""):
                return True
        except Exception:
            continue
    return tried == 0


# ---------------------------------------------------------------- 格式化
def _clean(v) -> str:
    """官网文本里常有换行/多余空白，压干净 —— 但**不改任何标点**，
    保持官方原文（它是事实，不能由我们改写)。
    """
    s = "" if v is None else str(v)
    return " ".join(s.split()).strip()


def score(obj: dict) -> tuple:
    """给一份官网原始返回打分（越大越全），用于在"同一站的多个编号"里挑最全那份。

    (-1,) 表示官网这条是空的（查无此站）—— 直接不参与比较。
    """
    if not str(obj.get("siteName") or "").strip():
        return (-1,)
    n_out = len(obj.get("outAndText") or [])
    n_tt = sum(len(obj.get(k) or []) for k in ("workDay", "dayoff", "holidays"))
    n_bus = len(obj.get("busInof") or [])
    # 简介写成"暂无数据"的那些编号，其它内容往往也是残缺的，拿来当附加分
    intro = 0 if str(obj.get("siteIntroduce") or "").strip() in ("", "暂无数据") else 1
    return (n_out, n_tt, n_bus, intro)


def fmt_exits(obj: dict) -> str:
    """outAndText → A1出入口：xxx（每口一行）"""
    lines = []
    for o in obj.get("outAndText") or []:
        name = _clean(o.get("outt"))
        text = _clean(o.get("textt"))
        if not name:
            continue
        lines.append("%s：%s" % (name, text if text else "无"))
    return "\n".join(lines)


def fmt_timetable(obj: dict) -> str:
    """workDay/dayoff/holidays →
        工作日 · 1号线：往罗湖 首06:02 末23:47；往机场东 首06:41 末23:21
    """
    out = []
    for key, label in SCHEDULE:
        for w in obj.get(key) or []:
            line = _clean(w.get("suoshuluxian"))
            segs = []
            # 上行（xinshifangxiang）
            d1 = _clean(w.get("xinshifangxiang"))
            if d1:
                segs.append("往%s 首%s 末%s" % (d1,
                            _clean(w.get("shoubanche")) or "--",
                            _clean(w.get("mobanche")) or "--"))
            # 下行（xinshifangxiangxia）
            d2 = _clean(w.get("xinshifangxiangxia"))
            if d2:
                segs.append("往%s 首%s 末%s" % (d2,
                            _clean(w.get("shoubanchexia")) or "--",
                            _clean(w.get("mobanchexia")) or "--"))
            if not segs:
                continue
            head = "%s · %s" % (label, line) if line else label
            out.append("%s：%s" % (head, "；".join(segs)))
    return "\n".join(out)


def fmt_bus(obj: dict) -> str:
    """busInof → B出入口 · 火车站：1、12、17、82"""
    lines = []
    for b in obj.get("busInof") or []:
        exit_name = _clean(b.get("chukou"))
        for bu in b.get("busOutInfo") or []:
            stop = _clean(bu.get("busName"))
            routes = _clean(bu.get("busInfo"))
            if not (stop or routes):
                continue
            head = "%s · %s" % (exit_name, stop) if exit_name else stop
            lines.append("%s：%s" % (head, routes))
    return "\n".join(lines)


# ---------------------------------------------------------------- 组装
def build_payload(data_dir: Path, src_dir: Path, only_fill_empty: bool = True):
    """返回 (items, report)

    items   : [{station_id, exits, timetable, bus_transfer}, ...]  只含要写的字段
    report  : 各种统计与未命中的站
    """
    idx = json.loads((src_dir / "stations_index.json").read_text(encoding="utf-8"))
    matched = idx.get("已命中", {})
    stations = json.loads((data_dir / "stations.json").read_text(
        encoding="utf-8"))["stations"]

    # 我们这边 站名 → station_id（★ station_id 就是站名）
    name_to_sid = {str(s.get("station_name", sid)).strip(): sid
                   for sid, s in stations.items()}

    items, rep = [], {
        "命中站数": 0, "查不到": idx.get("查不到", []),
        "原始文件缺失": [], "目标字段已有内容跳过": [], "空出口": 0, "空班次": 0,
        "空公交": 0, "名字在官网叫别的": [],
    }

    for name, info in sorted(matched.items()):
        sid = name_to_sid.get(name)
        if sid is None:                       # 官网有、我们数据里没有 → 不新建
            continue
        # ★★ 官网同一个站有好几个编号（换乘站每条线路一个），而且
        #   **不同编号返回的完整度不一样**：
        #     · 有的编号直接返回全空记录（银湖 0605 空 / 0923 才有数据）
        #     · 有的编号只有班次没出口（上梅林 0407 出口 0 / 0921 出口 4 + 真简介）
        #   所以**逐个编号读出来打分，取最全的那份**，不是"取第一个"。
        obj = None
        best = None
        for code in info.get("codes", [info.get("code")]):
            f = src_dir / "raw" / ("%s.json" % code)
            if not f.exists():
                continue
            cand = json.loads(f.read_text(encoding="utf-8"))
            s = score(cand)
            if s[0] < 0:
                continue
            if best is None or s > best:
                best, obj = s, cand
        if obj is None:
            rep["原始文件缺失"].append("%s(%s)" % (name, "/".join(
                info.get("codes", []))))
            continue

        api_name = str(obj.get("siteName") or "").strip()
        # ★ 官网的站名一般带"站"后缀（罗湖站），我们用的时候不带（罗湖）。
        #   但**我们这边也有本来就带"站"的名字**（宝安客运站），
        #   所以两种写法里只要有一种对上就算一致 —— 否则会报假警告。
        #   （早期版本写 replace("站","") 会把名字里所有的"站"都删掉，更糟。）
        if api_name and api_name != name and api_name.rstrip("站") != name:
            rep["名字在官网叫别的"].append({"我们": name, "官网": api_name})

        new = {
            "station_id": sid,
            "exits": fmt_exits(obj),
            "timetable": fmt_timetable(obj),
            "bus_transfer": fmt_bus(obj),
        }
        if not new["exits"]:
            rep["空出口"] += 1
        if not new["timetable"]:
            rep["空班次"] += 1
        if not new["bus_transfer"]:
            rep["空公交"] += 1

        # ★★ 用户定：只填空的，已有的一个字都不动
        existing = stations[sid]
        row = {"station_id": sid}
        skipped = []
        for k in TARGETS:
            old = str(existing.get(k) or "").strip()
            if only_fill_empty and old:
                skipped.append(k)
                continue
            if not new[k]:
                continue                       # 官网也没给 → 不写，别塞空串
            row[k] = new[k]
        if skipped:
            rep["目标字段已有内容跳过"].append("%s:%s" % (name, "+".join(skipped)))
        if len(row) > 1:
            items.append(row)
            rep["命中站数"] += 1

    return items, rep


# ---------------------------------------------------------------- 比对
def snapshots(stations: dict) -> dict:
    return {sid: {k: r.get(k) for k in (FROZEN + TEXT_KEEP)}
            for sid, r in stations.items()}


def diff_snapshots(a: dict, b: dict) -> list:
    bad = []
    for sid, before in a.items():
        if sid not in b:
            bad.append("%s 整条记录消失了" % sid)
            continue
        after = b[sid]
        for k, v in before.items():
            if after.get(k) != v:
                bad.append("%s.%s  %r → %r" % (sid, k, v, after.get(k)))
    for sid in b:
        if sid not in a:
            bad.append("%s 冒出来一条新记录" % sid)
    return bad


# ---------------------------------------------------------------- 导入动作
def do_import(data_dir: Path, items: list):
    """在指定数据目录上真跑一次 bulk_import（中途不关软件，因为是副本）。"""
    sys.path.insert(0, str(ROOT))
    import core.data_manager as DM
    DM.DATA_DIR = Path(data_dir)
    DM.STATIONS_FILE = Path(data_dir) / "stations.json"
    DM.LINES_FILE = Path(data_dir) / "lines.json"
    dm = DM.DataManager()
    return dm.bulk_import(items)


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--apply", action="store_true", help="真的写进软件数据")
    ap.add_argument("--force", action="store_true", help="检测不到进程也强行导入")
    ap.add_argument("--samples", type=int, default=0, help="打印 N 个站的成品")
    ap.add_argument("--overwrite", action="store_true",
                    help="★ 危险：允许覆盖已有内容（默认只填空的）")
    args = ap.parse_args()

    data_dir, src_dir = Path(args.data), Path(args.src)
    items, rep = build_payload(data_dir, src_dir,
                               only_fill_empty=not args.overwrite)

    print("=" * 74)
    print("官网数据 → %s" % data_dir)
    print("将写入 %d 站（字段：%s）" % (len(items), "、".join(TARGETS)))
    print("  官网查不到：%d 站（有轨电车/坪山云巴为主，保持原样不动）"
          % len(rep["查不到"]))
    print("  官网也没给出口的 %d 站 / 没给班次的 %d 站 / 没给公交的 %d 站（都不写，不留空串）"
          % (rep["空出口"], rep["空班次"], rep["空公交"]))
    if rep["目标字段已有内容跳过"]:
        print("  ★ 已有内容、按规矩跳过的：%d 站 %s"
              % (len(rep["目标字段已有内容跳过"]),
                 rep["目标字段已有内容跳过"][:5]))
    if rep["名字在官网叫别的"]:
        print("  ⚠ 名字与官网不一致（按我们这边站名落的）：%s"
              % rep["名字在官网叫别的"][:5])
    if rep["原始文件缺失"]:
        print("  ⚠ 缺原始文件：%d 个 %s"
              % (len(rep["原始文件缺失"]), rep["原始文件缺失"][:5]))
    print("=" * 74)

    if args.samples:
        stations = json.loads((data_dir / "stations.json").read_text(
            encoding="utf-8"))["stations"]
        for row in items[:args.samples]:
            sid = row["station_id"]
            print("\n──── %s ────" % sid)
            for k in TARGETS:
                v = row.get(k)
                if v:
                    print("  [%s]" % k)
                    for ln in v.split("\n")[:6]:
                        print("    " + ln)
                    if v.count("\n") >= 6:
                        print("    …（共 %d 行）" % (v.count("\n") + 1))
        return 0

    if not items:
        print("\n没有可写的内容，退出。")
        return 1

    # ---------------- 先在【临时副本】上真跑一遍（最硬的证据）----------------
    print("\n【演练】把数据拷到临时目录真跑一遍 bulk_import …")
    tmp = Path(tempfile.mkdtemp(prefix="szmc_rehearse_"))
    for f in ("stations.json", "lines.json"):
        shutil.copy2(data_dir / f, tmp / f)
    before_doc = json.loads((tmp / "stations.json").read_text(encoding="utf-8"))
    before_n = len(before_doc["stations"])
    before_snap = snapshots(before_doc["stations"])
    before_lines = (tmp / "lines.json").read_bytes()

    res = do_import(tmp, items)
    after_doc = json.loads((tmp / "stations.json").read_text(encoding="utf-8"))
    after_n = len(after_doc["stations"])
    after_lines = (tmp / "lines.json").read_bytes()

    problems = []
    if res["added"] != 0:
        problems.append("新增了 %d 条（必须是 0）" % res["added"])
    if res["failed"] != 0:
        problems.append("失败 %d 条" % res["failed"])
    if after_n != before_n:
        problems.append("站点数 %d → %d（必须不变）" % (before_n, after_n))
    if after_lines != before_lines:
        problems.append("lines.json 被改动了")
    d = diff_snapshots(before_snap, snapshots(after_doc["stations"]))
    problems.extend(d[:10])
    if len(d) > 10:
        problems.append("…共有 %d 处不该有的改动" % len(d))

    filled = sum(1 for s in after_doc["stations"].values()
                 if str(s.get("exits") or "").strip())
    tt = sum(1 for s in after_doc["stations"].values()
             if str(s.get("timetable") or "").strip())
    bt = sum(1 for s in after_doc["stations"].values()
             if str(s.get("bus_transfer") or "").strip())
    print("  写入结果：更新 %d / 新增 %d / 失败 %d"
          % (res["updated"], res["added"], res["failed"]))
    print("  填充后：出入口 %d/%d  首末班车 %d/%d  公交换乘 %d/%d"
          % (filled, after_n, tt, after_n, bt, after_n))
    if problems:
        print("\n  ✗ 演练发现问题，不会动真实数据：")
        for p in problems:
            print("     · " + p)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    print("  ✓ 演练通过：站点数不变、新增 0、冻结字段与已有文案 0 处改动、lines.json 未变")
    shutil.rmtree(tmp, ignore_errors=True)

    if not args.apply:
        print("\n【演练结束】加 --apply 才真导入（会先要求关掉 exe）。")
        return 0

    # ---------------- 真导入 ----------------
    print("\n【真导入】")
    running = exe_is_running()
    if running and not args.force:
        print("  ✗ 软件 SZ_MetroEditor.exe 还在运行 → 拒绝导入。")
        print("    请关掉软件再跑；确认检测有误才加 --force（有覆盖风险）。")
        return 1
    if running:
        print("  ⚠ 检测到软件在跑，但 --force 已给，继续（有被覆盖的风险）。")

    backup = ROOT / "_backup" / ("data_%s_官网导入前" % time.strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True, exist_ok=True)
    for f in ("stations.json", "lines.json"):
        shutil.copy2(data_dir / f, backup / f)
    print("  已备份 → %s" % backup)

    before = json.loads((data_dir / "stations.json").read_text(encoding="utf-8"))
    before_snap = snapshots(before["stations"])
    before_lines = (data_dir / "lines.json").read_bytes()

    res = do_import(data_dir, items)
    after = json.loads((data_dir / "stations.json").read_text(encoding="utf-8"))
    after_lines = (data_dir / "lines.json").read_bytes()

    bad = []
    if res["added"] != 0:
        bad.append("新增 %d 条（必须 0）" % res["added"])
    if len(after["stations"]) != len(before["stations"]):
        bad.append("站点数 %d → %d" % (len(before["stations"]),
                                       len(after["stations"])))
    if after_lines != before_lines:
        bad.append("lines.json 被改动")
    bad.extend(diff_snapshots(before_snap, snapshots(after["stations"])))

    if bad:
        print("\n  ✗ 导入后校验不通过，自动回滚：")
        for p in bad[:12]:
            print("     · " + p)
        for f in ("stations.json", "lines.json"):
            shutil.copy2(backup / f, data_dir / f)
        print("  已回滚到备份（%s）" % backup)
        return 1

    print("\n  ✓ 导入成功：更新 %d / 新增 %d / 失败 %d" %
          (res["updated"], res["added"], res["failed"]))
    n = len(after["stations"])
    for k in TARGETS:
        c = sum(1 for s in after["stations"].values() if str(s.get(k) or "").strip())
        print("     %-12s %d/%d" % (k, c, n))
    print("  备份留在 %s" % backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
