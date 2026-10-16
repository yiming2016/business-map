# -*- coding: utf-8 -*-
"""
校验「站点文案」批次文件（由 make_station_copy_batches.py 生成）。

为什么要单独校验：
    这批 txt 是要**整份转发给另一个 AI** 的，AI 会把其中那段 JSON 骨架原样
    补全后回传，再导回软件。所以这段 JSON 必须：
      (1) 能被 json.loads 解析（少一个大括号，整套流程就废了）；
      (2) 正好 8 条、每条只含约定的 6 个键、顺序对；
      (3) 所有创作字段还是 <FILL>（没被误填）；
      (4) 站点集合与软件真实数据**完全一致**（不多不少不重）——
          因为导入时 station_id 对不上就会"新建站点"，凭空多出孤儿站。
    另外校验参考信息表：站名/线路/换乘这些"事实"必须与 stations.json 一致，
    否则等于把错的前提发给 AI。

用法：
    python tools/check_station_copy_batches.py
    python tools/check_station_copy_batches.py --dir ../源码/站点文案 --data-dir ../软件/data
"""

import argparse
import io
import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]

EXPECT_KEYS = ["station_id", "station_name", "description",
               "landmarks", "notes", "facilities"]
CREATIVE = ["description", "landmarks", "notes", "facilities"]
FACTUAL = ["exits", "open_date"]          # 本批不该出现
PLACEHOLDER = "<FILL>"

# 参考表里每行形如：  机场东        1号线 11号线 12号线    是      1号线：… → **[本站]** → 后瑞
REF_ROW = re.compile(r"^  (\S+)\s{2,}(\S.*?)\s{2,}(是|否)\s{2,}(.*)$")


def load_json(p):
    with io.open(p, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def extract_skeleton(text):
    """从 txt 里抠出 {"stations": [ … ]} 那一段（含首尾行）。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == '{"stations": [':
            start = i
            break
    if start is None:
        return None, "找不到 JSON 骨架起始行 '{\"stations\": ['"
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "]}":
            return "\n".join(lines[start:j + 1]), None
    return None, "找不到 JSON 骨架结束行 ']}'"


def parse_ref_table(text):
    """返回 [(站名, '1号线 2号线', True/False, 相邻站说明), ...]"""
    rows = []
    seen_header = False
    for ln in text.splitlines():
        if ln.startswith("  站名") and "换乘" in ln:
            seen_header = True
            continue
        if not seen_header:
            continue
        if ln.startswith("="):        # 表结束
            break
        body = ln[2:] if ln.startswith("  ") else ln
        body = body.strip()
        if not body or body.startswith("·"):
            continue
        parts = re.split(r"\s{2,}", body)
        # parts: 站名 / 线路 / 是|否 / 相邻站（相邻站可能被换行拆到后续行，这里只取首行）
        if len(parts) >= 4 and parts[2] in ("是", "否"):
            rows.append((parts[0], parts[1], parts[2] == "是", parts[3]))
    return rows


def main():
    ap = argparse.ArgumentParser(description="校验站点文案批次文件")
    ap.add_argument("--dir", default=str(SRC / "站点文案"),
                    help="批次文件目录（默认 源码/站点文案）")
    ap.add_argument("--data-dir", default=str(SRC.parent / "软件" / "data"),
                    help="真实数据目录（默认 软件/data）")
    ap.add_argument("--batch", type=int, default=8, help="每批站点数（默认 8）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.dir)
    data_dir = Path(args.data_dir)

    real = load_json(data_dir / "stations.json")["stations"]
    line_list = load_json(data_dir / "lines.json")["lines"]
    line_name = {ln.get("id"): (ln.get("name") or ln.get("id")) for ln in line_list}
    real_ids = set(real)

    files = sorted([p for p in out_dir.glob("批次*.txt")])
    if not files:
        print("!! 目录里没有 批次*.txt：%s" % out_dir)
        return 2

    problems = []
    covered = []
    sizes = []
    per_file_rows = {}
    ref_mismatch = []

    for p in files:
        with io.open(p, "r", encoding="utf-8-sig") as f:
            text = f.read()
        sizes.append((p.name, len(text.encode("utf-8"))))

        # ---- 1. JSON 骨架能不能解析 ----
        block, err = extract_skeleton(text)
        if err:
            problems.append((p.name, err))
            continue
        try:
            obj = json.loads(block)
        except Exception as e:
            problems.append((p.name, "JSON 解析失败: %s" % e))
            continue
        if not isinstance(obj, dict) or list(obj.keys()) != ["stations"]:
            problems.append((p.name, "顶层不是 {\"stations\": [...]}"))
            continue

        rows = obj["stations"]
        per_file_rows[p.name] = len(rows)

        # ---- 2. 条数与键 ----
        # 均分模式下批次大小是 7~8 这个区间（不是恒等于 8），所以这里只卡"非空"，
        # 大小是否合理放到收尾处按"均分应有的区间"统一判。
        if not rows:
            problems.append((p.name, "本批 0 个站点"))
        elif len(rows) > args.batch:
            problems.append((p.name, "本批站点数 %d 超过上限 %d" % (len(rows), args.batch)))
        for k, r in enumerate(rows):
            if not isinstance(r, dict):
                problems.append((p.name, "第 %d 条不是对象" % (k + 1)))
                continue
            if list(r.keys()) != EXPECT_KEYS:
                problems.append((p.name, "第 %d 条键不对: %s" % (k + 1, list(r.keys()))))
            for f2 in FACTUAL:
                if f2 in r:
                    problems.append((p.name, "第 %d 条混进了事实字段 %s" % (k + 1, f2)))
            for f2 in CREATIVE:
                if f2 in r and r[f2] != PLACEHOLDER:
                    problems.append((p.name, "第 %d 条 %s 不是 <FILL>（生成阶段不该有内容）"
                                     % (k + 1, f2)))
            sid = r.get("station_id")
            if sid not in real_ids:
                problems.append((p.name, "第 %d 条 station_id=%r 不在真实数据里（会导致新建站点）"
                                 % (k + 1, sid)))
            elif r.get("station_name") != (real[sid].get("station_name") or sid):
                problems.append((p.name, "第 %d 条 station_name 与数据不符: %r"
                                 % (k + 1, r.get("station_name"))))
            covered.append(sid)

        # ---- 3. 参考表的事实必须与真实数据一致 ----
        for (nm, lns_txt, is_transfer, _nb) in parse_ref_table(text):
            if nm not in real:
                ref_mismatch.append((p.name, "参考表站名 %r 不在数据里" % nm))
                continue
            d = real[nm]
            want = [line_name.get(x, x) for x in (d.get("lines") or [])]
            got = [x for x in lns_txt.split() if x]
            if want and sorted(want) != sorted(got):
                ref_mismatch.append((p.name, "%s 线路不符: 数据 %s / 参考表 %s"
                                     % (nm, want, got)))
            if bool(d.get("is_transfer")) != is_transfer:
                ref_mismatch.append((p.name, "%s 换乘标记不符: 数据 %s / 参考表 %s"
                                     % (nm, bool(d.get("is_transfer")), is_transfer)))

    # ---- 汇总 ----
    dup = sorted({x for x in covered if covered.count(x) > 1})
    covered_set = set(covered)
    missing = sorted(real_ids - covered_set)
    extra = sorted(covered_set - real_ids)

    # 均分模式下每批大小的合理区间（379 个站分 48 批 → 每批 7~8 个）
    nb = len(per_file_rows)
    lo, hi = (0, 0)
    if nb:
        lo, hi = len(covered_set) // nb, len(covered_set) // nb
        if len(covered_set) % nb:
            hi += 1
        for nm, sz in sorted(per_file_rows.items()):
            if sz and sz < lo:
                problems.append((nm, "本批只有 %d 个站点，低于均分应有的 %d~%d"
                                 % (sz, lo, hi)))

    print("=" * 70)
    print("站点文案批次校验")
    print("=" * 70)
    print("批次文件数      : %d" % len(files))
    print("单文件大小      : %.1f~%.1f KB" % (min(s for _, s in sizes) / 1024.0,
                                              max(s for _, s in sizes) / 1024.0))
    dist = {}
    for v in per_file_rows.values():
        dist[v] = dist.get(v, 0) + 1
    print("批次大小分布    : %s"
          % (" / ".join("%d个站 × %d 批" % (k, v) for k, v in sorted(dist.items(),
                                                                 reverse=True)) or "无"))
    print("均分应有区间    : %d~%d 个/批" % (lo, hi) if nb else "均分应有区间    : -")
    print("覆盖站点（含重）: %d   去重后: %d" % (len(covered), len(covered_set)))
    print("真实数据站名数  : %d" % len(real_ids))
    print("与真实数据一致  : %s" % (covered_set == real_ids))
    print("重复站点        : %s" % (dup or "无 ✅"))
    print("缺失站点        : %s" % (missing or "无 ✅"))
    print("多余站点        : %s" % (extra or "无 ✅"))
    print("参考表事实问题  : %s" % (ref_mismatch or "无 ✅"))
    print("结构问题清单    : %s" % (problems or "无 ✅"))

    if args.verbose and problems:
        for nm, msg in problems[:20]:
            print("   - %s: %s" % (nm, msg))

    ok = (not problems and not dup and not missing and not extra
          and not ref_mismatch and covered_set == real_ids)
    print("-" * 70)
    print("结论: %s" % ("全部通过 ✅ 这批文件可以整份转发给另一个 AI"
                     if ok else "有问题 ❌ 见上面的清单"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
