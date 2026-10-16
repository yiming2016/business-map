# -*- coding: utf-8 -*-
"""
检查「批量导入」的读文件容错：带 BOM 的 UTF-8 / UTF-16 / GBK 都要能读。

背景（真实会踩的坑）：用户把 AI 回的 JSON 用记事本另存，不同版本的"编码"
下拉会写出 UTF-8、UTF-8 带 BOM、甚至 UTF-16。原代码写死 encoding="utf-8"，
遇到带 BOM 的会直接抛 "Unexpected UTF-8 BOM"，报错信息完全不知所云。

本脚本验证 ui/main_window.py 里的 read_text_file_smart()，
并顺带验证导入入口那段"拆 {\"stations\": [...]}"的逻辑。

用法：python tools/_chk_import_encoding.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("✅" if ok else "❌", name, ("  " + detail) if detail else ""))


SAMPLE = {"stations": [
    {"station_id": "机场东", "station_name": "机场东",
     "description": "位于宝安机场片区。", "landmarks": "宝安国际机场、机场码头",
     "notes": "行李多的乘客建议留出时间。", "facilities": "无障碍电梯"},
    {"station_id": "宝安中心", "station_name": "宝安中心",
     "description": "宝安中心区中枢。", "landmarks": "宝安区政府",
     "notes": "换乘站，方向感清晰。", "facilities": ""},
]}


def main() -> int:
    from ui.main_window import read_text_file_smart          # 被测函数本体

    tmp = Path(tempfile.mkdtemp(prefix="wbimport_"))
    text = json.dumps(SAMPLE, ensure_ascii=False, indent=2)

    cases = [
        ("UTF-8 无 BOM", text.encode("utf-8")),
        ("UTF-8 带 BOM（记事本另存）", b"\xef\xbb\xbf" + text.encode("utf-8")),
        ("UTF-16 LE 带 BOM（记事本 Unicode）", text.encode("utf-16")),
        ("UTF-16 BE 带 BOM", b"\xfe\xff" + text.encode("utf-16-be")),
        ("GBK（老编辑器）", text.encode("gbk")),
    ]

    for i, (name, raw) in enumerate(cases):
        p = tmp / ("case_%02d.json" % i)
        p.write_bytes(raw)
        try:
            got = read_text_file_smart(p)
            obj = json.loads(got)
            items = obj["stations"] if isinstance(obj, dict) and "stations" in obj else obj
            ok = (isinstance(items, list) and len(items) == 2
                  and items[0]["station_id"] == "机场东"
                  and "无障碍电梯" in items[0]["facilities"])
            record("%s → 读出并解析成 %d 条" % (name, len(items) if ok else -1),
                   ok, "" if ok else "读出来的内容不对")
        except Exception as e:
            record(name, False, "异常：%s: %s" % (type(e).__name__, e))

    # 对照：老写法（写死 utf-8）在读带 BOM 的文件时确实会失败 —— 证明这个改动不是多余的
    p = tmp / "bom.json"
    p.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    old_failed = False
    try:
        with open(p, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        old_failed = "BOM" in str(e) or "BOM" in repr(e)
    record("对照：老写法读带 BOM 文件会报错（说明改动必要）", old_failed,
           "" if old_failed else "老写法居然没报错？")

    # 拆 {"stations": [...]} 那段逻辑（导入入口用的就是它）
    obj = json.loads(read_text_file_smart(p))
    items = obj["stations"] if isinstance(obj, dict) and "stations" in obj else obj
    record("{\"stations\": [...]} 被正确拆成 list", isinstance(items, list) and len(items) == 2)

    bad = [n for n, ok in RESULTS if not ok]
    print("=" * 60)
    print("共 %d 项，通过 %d 项，失败 %d 项" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    print("结论：%s" % ("导入读文件的编码容错都正常 ✅" if not bad else "有问题 ❌"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
