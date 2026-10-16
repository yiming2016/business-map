# -*- coding: utf-8 -*-
"""
import_ai_reply.py —— 把归一好的文案 JSON **真正导入**进软件数据。

流水线最后一棒：`make_…batches` → AI 回传 → `merge_ai_replies.py`
→ `check_ai_reply.py`（含 --rehearse）→ **本脚本**。

★★ 三条硬规矩（都是踩出来的）：
  1. **导入前必须先关掉正在运行的 exe**。软件内存里还装着旧数据，
     只要它随手 `_save_data()` 一次就把你刚导入的结果**覆盖回旧的**。
     本脚本会先用 tasklist 查，发现还在跑就直接拒绝。
  2. **导入前先备份，失败可自动回滚**。备份放在
     `源码/_backup/data_<时间戳>_导入前/`，还原就是把两个 json 拷回去。
  3. **导入后必须验证"除了文案字段，别的都没动"** ——
     站点数不变、新增 0、**坐标 x/y / lines / is_transfer 逐字段深比**、
     lines.json 字节级不变。任何一条不对就自动回滚。

用法：
    python tools/import_ai_reply.py --reply 站点文案/_导入包_20260924.json
    python tools/import_ai_reply.py --reply ... --dry-run      # 只报告不改
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SRC.parent / "软件" / "data"

TEXT_FIELDS = ["description", "landmarks", "notes", "facilities"]
# ★ 这些字段一个字都不许动（坐标/线路归属/换乘是事实，不是文案）
FROZEN = ["x", "y", "lines", "is_transfer", "open_date", "exits", "station_name"]


def exe_is_running() -> bool:
    """查软件是不是还在跑。

    ★ 查不到时按【还在跑】处理（保守）：宁可让用户手动加 --force，
      也不能误判成"没跑"——那样导入完会被软件的一次随手保存覆盖回旧的。
    """
    tried = 0
    for cmd in (
        ["tasklist"],
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Name SZ_MetroEditor -ErrorAction SilentlyContinue)"
         "| Out-String"],
    ):
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=25)
            tried += 1
            raw = p.stdout
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            if "SZ_MetroEditor" in (raw or ""):
                return True
        except Exception:
            continue
    return tried == 0           # 一条都没跑成功 → 当作"还在跑"，要求 --force


def snapshot(stations: dict) -> dict:
    return {sid: {k: r.get(k) for k in FROZEN} for sid, r in stations.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="把文案 JSON 真正导入软件数据")
    ap.add_argument("--reply", required=True)
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA))
    ap.add_argument("--dry-run", action="store_true", help="只报告，不改数据")
    ap.add_argument("--force", action="store_true",
                    help="exe 还在跑也强行导入（不推荐，会被覆盖回去）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    st_file = data_dir / "stations.json"
    ln_file = data_dir / "lines.json"

    rows = json.loads(Path(args.reply).read_text(encoding="utf-8-sig"))["stations"]
    print("待导入：%d 条（%s）" % (len(rows), args.reply))

    # ---------- ① 运行中的 exe ----------
    if exe_is_running() and not args.force:
        print("\n❌ 检测到 SZ_MetroEditor.exe 还在运行。")
        print("   它内存里是旧数据，随手保存一次就会把你导入的结果覆盖回旧的。")
        print("   请先关掉软件再跑本脚本（--force 可强行，但不推荐）。")
        return 1
    if exe_is_running():
        print("\n⚠️  exe 仍在运行，但你加了 --force，继续。")

    # ---------- ② 备份 ----------
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = SRC / "_backup" / ("data_%s_导入前" % ts)
    if not args.dry_run:
        bak.mkdir(parents=True, exist_ok=True)
        for f in (st_file, ln_file):
            if f.exists():
                shutil.copy2(f, bak / f.name)
        print("已备份 → %s（%s）"
              % (bak, "、".join(p.name for p in sorted(bak.iterdir()))))

    # ---------- ③ 导入前的现场 ----------
    before_doc = json.loads(st_file.read_text(encoding="utf-8-sig"))
    before = before_doc["stations"]
    snap_before = snapshot(before)
    ln_before = ln_file.read_bytes()

    unknown = [r["station_id"] for r in rows if r["station_id"] not in before]
    if unknown:
        print("\n❌ 有不认识的 station_id（会新建孤儿站）：%s" % unknown[:10])
        return 1
    print("对照真实数据：379→ 现有 %d 个站点，陌生 id %d 个" % (len(before), len(unknown)))

    if args.dry_run:
        print("\n[dry-run] 只报告，未改动任何数据。")
        return 0

    # ---------- ④ 真导入 ----------
    sys.path.insert(0, str(SRC))
    import core.data_manager as DM
    DM.DATA_DIR = data_dir
    DM.STATIONS_FILE = st_file
    DM.LINES_FILE = ln_file
    DM._data_manager = None
    dm = DM.get_data_manager()
    res = dm.bulk_import(rows)
    print("\n导入结果：新增 %d / 更新 %d / 失败 %d"
          % (res["added"], res["updated"], res["failed"]))

    # ---------- ⑤ 验证 ----------
    after_doc = json.loads(st_file.read_text(encoding="utf-8-sig"))
    after = after_doc["stations"]
    problems = []

    if len(after) != len(before):
        problems.append("站点数变了：%d → %d" % (len(before), len(after)))
    if res["added"] != 0:
        problems.append("新增了 %d 个站点（不该有）" % res["added"])

    snap_after = snapshot(after)
    moved = []
    for sid in snap_before:
        if sid not in snap_after:
            problems.append("站点丢了：%s" % sid)
            continue
        for k in FROZEN:
            if snap_before[sid][k] != snap_after[sid][k]:
                moved.append("%s.%s" % (sid, k))
    if moved:
        problems.append("冻结字段被改动：%s" % moved[:8])

    if ln_file.read_bytes() != ln_before:
        problems.append("lines.json 被改动了（不该动）")

    filled = {k: sum(1 for r in after.values() if (r.get(k) or "").strip())
              for k in TEXT_FIELDS}
    ids = {r["station_id"] for r in rows}
    not_written = [sid for sid in ids
                   if any((after[sid].get(k) or "") != (r.get(k) or "")
                          for r in rows if r["station_id"] == sid
                          for k in TEXT_FIELDS)]
    if not_written:
        problems.append("有 %d 个站的文案没写进去：%s"
                        % (len(not_written), not_written[:5]))

    print("\n---- 验证 ----")
    print("  站点数        %d → %d" % (len(before), len(after)))
    print("  新增站点      %d（必须为 0）" % res["added"])
    print("  冻结字段改动  %d 处（必须为 0）：坐标/线路/换乘/open_date/exits/站名"
          % len(moved))
    print("  lines.json    %s（必须未变）"
          % ("未变 ✅" if ln_file.read_bytes() == ln_before else "变了 ❌"))
    print("  文案填充情况  " + "  ".join(
        "%s %d/%d" % (k, filled[k], len(after)) for k in TEXT_FIELDS))

    if problems:
        print("\n❌ 验证不通过，自动回滚：")
        for p in problems:
            print("   · %s" % p)
        for f in (st_file, ln_file):
            src = bak / f.name
            if src.exists():
                shutil.copy2(src, f)
        print("   已还原到备份 %s" % bak)
        return 1

    print("\n[OK] 导入完成 ✅")
    print("     备份在 %s" % bak)
    print("     回滚：把备份里的两个 json 拷回 %s 即可" % data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
