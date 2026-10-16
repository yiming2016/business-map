# -*- coding: utf-8 -*-
"""
merge_ai_replies.py —— 把 AI 回传的**各种杂格式**归一成一份可导入的 JSON。

为什么需要它：
    分批发给别的 AI，回来的格式**每次都不一样** —— 这次就三种：
      ① 多行缩进的 JSON 块（每批一个 {"stations": [...]}）
      ② 纯文本资料卡（■ 站名（站名）+ 简介/周边地标/备注/设施）
      ③ 前半文本卡 + 末尾若干 JSON 块
    软件的「批量导入」只认一种 JSON，所以先把它们归一，再统一校验、统一导入。

★ 三条铁律（见 README「站点文案批处理」）：
    1. **station_id 原样照抄** —— `bulk_import` 里是
       `sid = row.get("station_id") or generate_station_id(...)`，
       id 写错就是**新建一个孤儿站**。所以这里拿它跟真实 stations.json 逐个对，
       对不上直接报错停下，绝不"猜一个近似的"。
    2. **参考数据（lines / is_transfer）绝不能进 JSON** —— `upsert_station` 是
       合并写入，把线路归属塞进去会把真实数据覆盖掉。本脚本只输出 4 个文案字段。
    3. **事实字段（exits / open_date）不给就不动** —— AI 没提供的字段不出现在
       输出里，导入时自然保持原值，不会编造。

占位符处理：`（未填写）` / `未填写` / `无` / `-` 这类一律归一成空串，
绝不把"未填写"三个字写进数据。

用法：
    python tools/merge_ai_replies.py <回传1.txt> [回传2.txt ...] \
           --out 站点文案/_导入包_20260924.json [--data-dir 软件/data]

只写输出文件，**不碰真实数据**；导入是下一步的事（且必须先关掉正在运行的 exe）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from json import JSONDecoder
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]

# 允许写进输出的字段（★ 不含 lines / is_transfer / exits / open_date）
FIELDS = ["station_id", "station_name", "description", "landmarks", "notes", "facilities"]
TEXT_FIELDS = ["description", "landmarks", "notes", "facilities"]

# 文本卡的行标签 → 字段名
LABEL2FIELD = {"简介": "description", "周边地标": "landmarks",
               "备注": "notes", "设施": "facilities"}

# 占位符：出现这些就当"没内容"
PLACEHOLDERS = {"", "（未填写）", "(未填写)", "未填写", "无", "暂无", "无。",
                "-", "—", "–", "／", "/", "N/A", "n/a"}

_DEC = JSONDecoder()


# ----------------------------------------------------------------------
# 抽取
# ----------------------------------------------------------------------
def scan_json_blocks(text: str):
    """扫出文本里所有能解析的 JSON 对象块（容忍前后包裹的说明文字）。"""
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        try:
            obj, end = _DEC.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        out.append(obj)
        i = end
    return out


def collect_from_json(text: str, sink: dict, src: str, report: list) -> int:
    got = 0
    for obj in scan_json_blocks(text):
        rows = obj.get("stations") if isinstance(obj, dict) else None
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                report.append("%s：块里有非对象记录，已跳过" % src)
                continue
            sid = (r.get("station_id") or "").strip()
            if not sid:
                report.append("%s：有条记录没有 station_id，已跳过" % src)
                continue
            if sid in sink:
                report.append("%s：station_id 重复 → %s（保留先出现的）" % (src, sid))
                continue
            sink[sid] = {k: str(r.get(k, "") or "").strip() for k in FIELDS}
            sink[sid]["station_id"] = sid
            got += 1
    return got


def collect_from_cards(text: str, sink: dict, src: str, report: list) -> int:
    """解析 ■ 站名（站名）+ 简介/周边地标/备注/设施 这种文本资料卡。"""
    got = 0
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*■\s*(.+?)\s*[（(](.+?)[）)]\s*$", line)
        if m:
            name, inparen = m.group(1).strip(), m.group(2).strip()
            if name != inparen:
                report.append("%s：卡片标题站名与括号内容不一致 → %s / %s"
                              % (src, name, inparen))
            if name in sink:
                report.append("%s：station_id 重复 → %s（保留先出现的）" % (src, name))
                cur = None
                continue
            cur = {"station_id": name, "station_name": name,
                   "description": "", "landmarks": "", "notes": "", "facilities": ""}
            sink[name] = cur
            got += 1
            continue
        m = re.match(r"^\s*■\s*(.+?)\s*$", line)
        if m:                                   # 没有括号的写法
            name = m.group(1).strip()
            if name in sink:
                report.append("%s：station_id 重复 → %s（保留先出现的）" % (src, name))
                cur = None
                continue
            cur = {"station_id": name, "station_name": name,
                   "description": "", "landmarks": "", "notes": "", "facilities": ""}
            sink[name] = cur
            got += 1
            continue
        if cur is None:
            continue
        m = re.match(r"^\s*(简介|周边地标|备注|设施)\s*[：:]\s*(.*)$", line)
        if m:
            cur[LABEL2FIELD[m.group(1)]] = m.group(2).strip()
    return got


def normalize(sink: dict, report: list) -> None:
    """占位符 → 空串；station_name 空则补 station_id。"""
    for sid, row in sink.items():
        for k in TEXT_FIELDS:
            v = (row.get(k) or "").strip()
            if v in PLACEHOLDERS:
                row[k] = ""
        if not row.get("station_name"):
            row["station_name"] = sid
        row["station_id"] = sid


# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="把 AI 回传的杂格式归一成可导入 JSON")
    ap.add_argument("replies", nargs="+", help="回传 txt（可多个，格式可不同）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--data-dir", default=str(SRC.parent / "软件" / "data"),
                    help="真实数据目录（用来核对 station_id）")
    args = ap.parse_args()

    real_path = Path(args.data_dir) / "stations.json"
    real = json.loads(real_path.read_text(encoding="utf-8-sig"))["stations"]
    print("真实站点：%d 个（%s）" % (len(real), real_path))

    sink: dict = {}
    report: list = []
    print("\n---- 逐文件抽取 ----")
    for p in args.replies:
        path = Path(p)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        n_json = collect_from_json(text, sink, path.name, report)
        n_card = collect_from_cards(text, sink, path.name, report)
        print("  %-42s JSON 记录 %3d 条 + 文本卡 %3d 张"
              % (path.name, n_json, n_card))

    normalize(sink, report)

    # ---------------- 核对 station_id ----------------
    unknown = [s for s in sink if s not in real]
    missing = [s for s in real if s not in sink]
    print("\n---- 核对 ----")
    print("  抽到站点 %d 个 / 真实 %d 个" % (len(sink), len(real)))
    print("  ❌ 不认识的 station_id（会导致新建孤儿站）：%d" % len(unknown))
    for s in unknown[:20]:
        print("        %s" % s)
    print("  ⚠️  没被覆盖到的站点：%d" % len(missing))
    for s in missing[:20]:
        print("        %s" % s)

    # ---------------- 内容体检 ----------------
    print("\n---- 内容体检（4 个文案字段） ----")
    bad = 0
    for k in TEXT_FIELDS:
        empty = [s for s, r in sink.items() if not r.get(k)]
        fill = [len(r[k]) for s, r in sink.items() if r.get(k)]
        print("  %-11s 已填 %3d / %3d   字数 最短%d 最长%d 中位%d%s"
              % (k, len(fill), len(sink),
                 min(fill) if fill else 0, max(fill) if fill else 0,
                 sorted(fill)[len(fill) // 2] if fill else 0,
                 "   （空 %d：%s）" % (len(empty), "、".join(empty[:6])) if empty else ""))
    left_fill = sum(1 for r in sink.values()
                    for k in TEXT_FIELDS if "<FILL>" in (r.get(k) or ""))
    if left_fill:
        print("  ❌ 还有 %d 处 <FILL> 没填" % left_fill)
        bad += 1
    # 不该出现的字段
    for s, r in sink.items():
        extra = set(r) - set(FIELDS)
        if extra:
            print("  ❌ %s 混进了不该有的字段 %s" % (s, sorted(extra)))
            bad += 1
            break

    if report:
        print("\n---- 抽取过程中的提醒（%d 条） ----" % len(report))
        for r in report[:20]:
            print("  · %s" % r)

    if unknown or bad:
        print("\n结论：❌ 有问题，不写输出文件。")
        return 1
    if missing:
        print("\n结论：⚠️  有 %d 个站点没覆盖到 —— 仍会写出文件，但你得想清楚要不要导入。"
              % len(missing))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stations": [sink[s] for s in real if s in sink]}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8-sig")
    # ★★ 生成物必须过一遍真正的解析器（"看起来对" ≠ "能解析"）
    back = json.loads(out.read_text(encoding="utf-8-sig"))
    assert len(back["stations"]) == len(payload["stations"])

    print("\n[OK] 已写出 %s" % out)
    print("     站点 %d 条，utf-8-sig，回读解析通过 ✅" % len(back["stations"]))
    print("     下一步：python tools/check_ai_reply.py --reply \"%s\" --rehearse" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
