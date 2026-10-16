"""
tools/import_stations.py
========================
批量导入脚本（无 GUI）—— 给 AI 识别程序用的入口。

用法：
    python tools/import_stations.py --file <识别结果.json>
    python tools/import_stations.py --file <识别结果.json> --dry-run        # 只检查不写入
    python tools/import_stations.py --example                                # 生成示例
    python tools/import_stations.py --init <线路名> --color <#RRGGBB>      # 速添一条线路

数据文件位置：data/stations.json（自动与 GUI 软件共享，无需重启软件即可重新加载）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 把项目根目录加进 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_manager import get_data_manager  # noqa: E402


def cmd_file(args):
    dm = get_data_manager()
    path = Path(args.file)
    if not path.exists():
        print(f"[ERROR] 文件不存在：{path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        content = json.load(f)

    if isinstance(content, dict) and "stations" in content:
        items = content["stations"]
    else:
        items = content

    if not items:
        print("[WARN] 文件里没有 stations 列表（或对象）。")
        sys.exit(1)

    if args.dry_run:
        print(f"[DRY-RUN]  将导入 {len(items) if hasattr(items, '__len__') else '?'} 条站点")
        # 只校验，不写
        keys = list(items.keys()) if isinstance(items, dict) else [it.get("station_id", "?") for it in items]
        for k in keys[:10]:
            print(f"  - {k}")
        if len(keys) > 10:
            print(f"  ... 共 {len(keys)} 条")
        return

    res = dm.bulk_import(items)
    print(f"[OK] 新增 {res['added']} 条, 更新 {res['updated']} 条, 失败 {res['failed']} 条")
    print(f"  数据已写入：{PROJECT_ROOT / 'data' / 'stations.json'}")
    print(f"  现在共 {len(dm.all_stations())} 个站点（重启桌面软件即可看到新站点）")


def cmd_example(args):
    """生成一份符合 schema 的示例文件，方便 AI 参考格式。"""
    out_path = PROJECT_ROOT / "data" / "_example_import.json"
    example = {
        "_说明": "本文件可直接用 tools/import_stations.py --file data/_example_import.json 导入",
        "stations": [
            {
                "station_id": "1_DJWL",
                "station_name": "地铁大厦",
                "lines": ["1"],
                "x": 600,
                "y": 530,
                "is_transfer": False,
                "open_date": "2011-06-22",
                "description": "位于红岭南路与深南东路交汇处，是 1 号线沿线车站。",
                "exits": "A/B/C/D 四个出口",
                "facilities": "无障碍电梯",
                "landmarks": "地铁大厦",
                "notes": ""
            },
            {
                "station_id": "1_5_GZS",
                "station_name": "购物公园",
                "lines": ["1", "3"],
                "x": 760,
                "y": 520,
                "is_transfer": True,
                "open_date": "2011-06-22",
                "description": "1/3 号线换乘站，临近 COCO Park、购物公园。",
                "exits": "A 出口：购物公园；B 出口：COCO Park",
                "facilities": "无障碍电梯、卫生间、母婴室",
                "landmarks": "购物公园、COCO Park",
                "notes": ""
            }
        ]
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(example, f, ensure_ascii=False, indent=2)
    print(f"[OK] 示例文件已写入：{out_path}")
    print(f"     你可以修改后用 --file 参数导入。")


def cmd_init(args):
    dm = get_data_manager()
    dm.upsert_line(
        args.line,
        {"name": f"{args.line}号线", "alias": args.line, "color": args.color}
    )
    dm.save()
    print(f"[OK] 已新增线路 {args.line} 颜色 {args.color}")
    print(f"     现在共有 {len(dm.all_lines())} 条线路")


def main():
    parser = argparse.ArgumentParser(description="深圳地铁编辑器 - 数据导入工具（AI 识别结果批量入库入口）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_file = sub.add_parser("file", aliases=["import"], help="从 JSON 文件导入")
    p_file.add_argument("--file", required=True, help="JSON 文件路径")
    p_file.add_argument("--dry-run", action="store_true", help="只校验不写入")
    p_file.set_defaults(func=cmd_file)

    p_example = sub.add_parser("example", help="生成示例导入文件")
    p_example.set_defaults(func=cmd_example)

    p_init = sub.add_parser("init-line", help="快速新增一条线路")
    p_init.add_argument("--line", required=True, help="线路 ID，如 21")
    p_init.add_argument("--color", default="#888888", help="颜色 #RRGGBB")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
