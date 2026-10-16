# -*- coding: utf-8 -*-
"""_fix_orphan_stations.py —— 找出并（可选）清理"孤儿站点"。

什么叫孤儿站点：**不在任何一条线路上**的站点。
它既不在 `lines` 字段里挂线，也没有任何线路的 stations 列表引用它 ——
于是布线算法永远不会把它画进线路，它就是一个孤零零漂在地图上的灰点
（ui/map_view.reload_stations 里"没有线路 → 灰色 #555555"）。

它是怎么来的：地图上「双击空白处」（或开"添加模式"后单击空白处）会弹新建
站点对话框（ui/map_view.mouseDoubleClickEvent / mousePressEvent），
手一抖点了空地、又顺手点了保存，就留下一个名叫"新站点"、内容随手乱填的站点。

判定要两个条件都满足才算孤儿（只信 `lines` 字段不稳妥：数据和线路两边可能不一致）：
    ① 站点的 lines 字段为空
    ② 没有任何线路的 stations 列表引用它

★ 默认只报告、不动数据。真要删必须显式加 --apply。
★ --apply 会在数据目录旁写一份 `_removed_orphans_<时间戳>.json`，
  里面是被删除站点的完整原始数据 —— 想恢复就把它塞回 stations.json 的
  "stations" 字典里即可。

用法：
    python tools/_fix_orphan_stations.py                              # 只看（源码/data）
    python tools/_fix_orphan_stations.py --data-dir ..\\软件\\data      # 看打包版那份
    python tools/_fix_orphan_stations.py --data-dir ..\\软件\\data --apply
    python tools/_fix_orphan_stations.py --keep ST_6d974df0 --apply    # 点名保留某个
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.data_manager as DM


def referenced_ids(lines_doc) -> dict:
    """线路里引用到的所有站点 id → 出现在哪些线路上。"""
    ref = {}
    for ln in (lines_doc.get("lines") or []):
        for key in ("stations", "station_ids", "stop_ids", "stops"):
            v = ln.get(key)
            if isinstance(v, list):
                for sid in v:
                    if isinstance(sid, str):
                        ref.setdefault(sid, []).append(ln.get("id"))
    return ref


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None,
                    help="数据目录（默认 源码/data；打包版是 软件/data）")
    ap.add_argument("--apply", action="store_true", help="真的删除（默认只报告）")
    ap.add_argument("--keep", action="append", default=[],
                    help="点名保留的站点 id（可重复）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve() if args.data_dir \
        else (ROOT / "data").resolve()

    # ★ 把 DataManager 的读写目标改到指定目录（它默认认得是"程序自己所在目录"）
    DM.DATA_DIR = data_dir
    DM.STATIONS_FILE = data_dir / "stations.json"
    DM.LINES_FILE = data_dir / "lines.json"

    if not DM.STATIONS_FILE.exists():
        print("!! 找不到 %s" % DM.STATIONS_FILE)
        sys.exit(1)

    dm = DM.DataManager()
    stations = dm.all_stations()
    lines_doc = {"lines": dm.all_lines()}
    ref = referenced_ids(lines_doc)

    print("=" * 78)
    print("数据目录：%s" % data_dir)
    print("站点 %d 个，线路 %d 条" % (len(stations), len(lines_doc["lines"])))

    orphans = []
    for sid, st in stations.items():
        if (st.get("lines") or []):
            continue
        if sid in ref:
            continue                      # 线路里引用了它 → 不算孤儿
        orphans.append(sid)

    print("\n孤儿站点（lines 为空 且 没有任何线路引用）：%d 个" % len(orphans))
    if not orphans:
        print("  没有。数据是干净的 ✅")
        print("=" * 78)
        return

    for sid in orphans:
        st = stations[sid]
        print("\n  %s" % sid)
        print("    站名 : %s" % st.get("station_name"))
        print("    坐标 : (%s, %s)" % (st.get("x"), st.get("y")))
        print("    资料 : 描述=%r 出口=%r 换乘=%s" % (
            st.get("description"), st.get("exits"), st.get("is_transfer")))
        print("    建时 : %s" % st.get("_updated_at"))
        print("    原文 : %s" % json.dumps(st, ensure_ascii=False, sort_keys=True))

    keep = set(args.keep)
    todo = [s for s in orphans if s not in keep]
    if keep:
        print("\n点名保留（不动）：%s" % sorted(keep))
    if not todo:
        print("\n没有需要处理的对象。")
        print("=" * 78)
        return

    if not args.apply:
        print("\n【只报告，未改动任何数据】确认无误后加 --apply 执行删除。")
        print("=" * 78)
        return

    # ---------- 执行 ----------
    ts = time.strftime("%Y%m%d_%H%M%S")
    restore = data_dir / ("_removed_orphans_%s.json" % ts)
    removed = {}
    for sid in todo:
        removed[sid] = stations[sid]
    with open(restore, "w", encoding="utf-8") as f:
        json.dump({"removed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "data_dir": str(data_dir),
                   "stations": removed}, f, ensure_ascii=False, indent=2)
    print("\n已写恢复文件：%s" % restore)

    for sid in todo:
        dm.delete_station(sid)
        print("  已删除 %s （%s）" % (sid, removed[sid].get("station_name")))
    dm.save()
    print("\n已保存 stations.json（原文件被自动备份为 stations.json.bak）")
    print("现在站点 %d 个" % len(dm.all_stations()))
    print("=" * 78)


if __name__ == "__main__":
    main()
