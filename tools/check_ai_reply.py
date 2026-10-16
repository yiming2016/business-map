# -*- coding: utf-8 -*-
"""
校验「另一个 AI 回传的站点文案 JSON」。

用途：把 站点文案/批次NN.txt 发给别的 AI，它会回一段 JSON。**导入软件之前**
先跑这个脚本，把低级错误挡在门外 —— 因为导入是"合并写入"，
一个 station_id 写错就会凭空新建一个站点（历史上真出现过这种孤儿站）。

它会查四类东西：
  A. 能不能解析 / 形状对不对（兼容 BOM、UTF-16、```json 围栏）
  B. station_id 是否与批次文件里的**完全一致**（多了少了改了都是问题）
     且 station_name 与真实数据一致
  C. 内容是否踩了"禁忌"：营销词、预测规划、数字/价格/出口编号、emoji、
     Markdown、换行、字数超范围、8 条句式雷同
  D. （--rehearse）在**临时副本**上真跑一次导入：
     - 站点总数必须不变（导入前 379 → 导入后还是 379，新增必须为 0）
     - 本批这 8 个站的字段确实被写进去了
     - **其余站点必须一个字节都没动**（防止误覆盖线路归属）

用法：
    # 只做 A/B/C 检查
    python tools/check_ai_reply.py --reply 站点文案/回复/批次01.json --batch 站点文案/批次01.txt

    # 再加一步：在临时副本上真跑一遍导入（不会碰真实数据）
    python tools/check_ai_reply.py --reply ... --batch ... --rehearse

    # 一次校验一个目录下所有回复
    python tools/check_ai_reply.py --reply-dir 站点文案/回复
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

EXPECT_KEYS = ["station_id", "station_name", "description",
               "landmarks", "notes", "facilities"]
CREATIVE = ["description", "landmarks", "notes", "facilities"]
PLACEHOLDER = "<FILL>"

# 字数要求（宽松带 = 允许范围，超出只提示；严格带 = 判问题）
LEN_SPEC = {
    "description": (60, 110, 45, 140),
    "landmarks": (20, 40, 10, 60),
    "notes": (20, 40, 10, 60),
    "facilities": (0, 25, 0, 40),
}

MARKETING = ["绝佳", "必打卡", "打卡", "超值", "首选", "火爆", "天花板", "不容错过",
             "独一无二", "闻名", "之最", "最佳", "顶级", "人气爆棚", "网红"]
PREDICT = ["将建成", "即将开通", "未来会有", "规划中的", "规划中", "预计", "有望",
           "将来", "马上开通", "下一步将"]
# 数字：允许线路名、航站楼号、营业时长这类**本来就该带数字**的地名/事实，
# 其余数字（票价、客流、日期、距离…）都算"AI 编的具体事实" → 报出来。
# ★ 2026-09-24 修：原来只认 "N号线"，于是
#     "1、11、12号线交汇"（顿号分隔的多个号）、
#     "T3航站楼"（航站楼编号）、
#     "24小时通关口岸"（口岸真实属性）
#   全被误报成"价格/客流/日期" —— 删掉它们反而丢掉必要信息。
LINE_NUM = re.compile(
    r"\d+\s*(?:[、,，/和与及]\s*\d+\s*)*号线"   # 1号线 / 1、5、11号线交汇
    r"|T\s*\d+"                                 # T3 航站楼
    r"|\d+\s*小时"                              # 24小时通关
)
ANY_DIGIT = re.compile(r"\d")
EXIT_LETTER = re.compile(r"[A-Ha-h]\s*口")
MD_TOKEN = re.compile(r"```|\*\*|^#{1,6}\s|^\s*[-*+]\s|\[[^\]]*\]\(")
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF"
    "\U0000FE00-\U0000FE0F\U00002190-\U000021FF\U00002B00-\U00002BFF]")


# ---------------------------------------------------------------- 读文件
def read_text_smart(path: Path) -> str:
    """兼容 UTF-8(BOM) / UTF-16 / GBK —— 记事本另存出来什么都可能有。"""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def strip_fence(text: str) -> str:
    """剥掉 AI 不听话加的 ```json 围栏 / 前后废话。

    ★ 这里有个坑（踩过）：不能无脑"从第一个 { 或 [ 开始"截。
      一个合法对象是 {"stations": [ ... ]}，`{` 在下标 0 会被跳过，
      然后就会撞上内部的 `[` 把 JSON 从中间截断。
      所以必须先判断"是不是已经以 { 或 [ 开头"，是的话就别动。
    """
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    if s[:1] not in ("{", "["):                 # 前面还挂着说明文字才截
        idx = [i for i in (s.find("{"), s.find("[")) if i != -1]
        if idx:
            s = s[min(idx):]
    j = max(s.rfind("}"), s.rfind("]"))         # 结尾多出来的话也去掉
    if j != -1:
        s = s[:j + 1]
    return s.strip()


def load_reply(path: Path):
    text = read_text_smart(path)
    for candidate in (strip_fence(text), text.strip()):
        try:
            return json.loads(candidate), None
        except Exception as e:
            last = e
    return None, str(last)


def extract_rows(obj):
    """把回复归一成 list[dict]。"""
    if isinstance(obj, dict):
        if isinstance(obj.get("stations"), list):
            return obj["stations"]
        if isinstance(obj.get("stations"), dict):        # 有人会回成字典
            out = []
            for sid, body in obj["stations"].items():
                row = dict(body) if isinstance(body, dict) else {"description": body}
                row.setdefault("station_id", sid)
                out.append(row)
            return out
        # 顶层直接是 {站名: {...}}
        if all(isinstance(v, dict) for v in obj.values()):
            out = []
            for sid, body in obj.items():
                row = dict(body)
                row.setdefault("station_id", sid)
                out.append(row)
            return out
    if isinstance(obj, list):
        return obj
    return []


def extract_batch_ids(batch_path: Path):
    """从批次 txt 里抠出骨架里的 station_id 顺序。"""
    text = read_text_smart(batch_path)
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == '{"stations": ['), None)
    if start is None:
        return None
    block = []
    for ln in lines[start:]:
        block.append(ln)
        if ln.strip() == "]}":
            break
    try:
        obj = json.loads("\n".join(block))
    except Exception:
        return None
    return [r.get("station_id") for r in obj.get("stations", [])]


# ---------------------------------------------------------------- 检查
def check_content(rows, batch_ids, real):
    """返回 (问题列表, 提示列表)。"""
    problems, notes = [], []

    # --- 条数与顺序 ---
    ids = [r.get("station_id") for r in rows]
    if batch_ids is not None:
        if len(rows) != len(batch_ids):
            problems.append("条数 %d ≠ 批次文件里的 %d" % (len(rows), len(batch_ids)))
        miss = [x for x in batch_ids if x not in ids]
        extra = [x for x in ids if x not in batch_ids]
        if miss:
            problems.append("★ 少了这些站点：%s" % miss)
        if extra:
            problems.append("★ 多了这些站点（会新建孤儿站）：%s" % extra)
        if sorted(ids) != sorted(batch_ids) and not miss and not extra:
            notes.append("顺序与批次文件不同（不影响导入，但建议照抄原顺序）")

    seen = set()
    for k, r in enumerate(rows, start=1):
        tag = "第%d条(%s)" % (k, r.get("station_id") or "?")
        if not isinstance(r, dict):
            problems.append("%s 不是对象" % tag)
            continue
        ks = list(r.keys())
        if ks != EXPECT_KEYS:
            problems.append("%s 键不对：%s（应为 %s）" % (tag, ks, EXPECT_KEYS))
        sid = r.get("station_id")
        if sid in seen:
            problems.append("%s station_id 重复出现" % tag)
        seen.add(sid)

        # 站名与真实数据一致
        if real and sid in real:
            want = real[sid].get("station_name") or sid
            if r.get("station_name") != want:
                problems.append("%s station_name=%r 与数据里 %r 不符"
                                % (tag, r.get("station_name"), want))
        elif real and sid not in real:
            problems.append("%s station_id=%r 不在真实数据里" % (tag, sid))

        for f in ("exits", "open_date"):
            if f in r:
                problems.append("%s 混进了事实字段 %s（本批不该有）" % (tag, f))

        # 逐字段内容
        for f in CREATIVE:
            v = r.get(f, "")
            if not isinstance(v, str):
                problems.append("%s %s 不是字符串" % (tag, f))
                continue
            if v.strip() == PLACEHOLDER:
                problems.append("%s %s 还是 <FILL>，AI 漏填了" % (tag, f))
                continue
            if v == "":
                if f in ("description", "landmarks"):
                    problems.append("%s %s 是空的（这一栏应必填）" % (tag, f))
                continue
            if "\n" in v or "\r" in v:
                problems.append("%s %s 里有换行" % (tag, f))
            if MD_TOKEN.search(v):
                problems.append("%s %s 里有 Markdown 符号" % (tag, f))
            if EMOJI.search(v):
                problems.append("%s %s 里有 emoji/符号" % (tag, f))
            for w in MARKETING:
                if w in v:
                    problems.append("%s %s 用了营销词「%s」" % (tag, f, w))
            for w in PREDICT:
                if w in v:
                    problems.append("%s %s 用了预测词「%s」" % (tag, f, w))
            stripped = LINE_NUM.sub("", v)
            if ANY_DIGIT.search(stripped):
                problems.append("%s %s 里有数字（价格/客流/日期？）：%s"
                                % (tag, f, ANY_DIGIT.search(stripped).group()))
            if EXIT_LETTER.search(v):
                problems.append("%s %s 提到出口编号：%s" % (tag, f, EXIT_LETTER.search(v).group()))
            ln_ = len(v)
            lo, hi, hard_lo, hard_hi = LEN_SPEC.get(f, (0, 999, 0, 999))
            if ln_ < hard_lo or ln_ > hard_hi:
                problems.append("%s %s 字数 %d，远超要求 %d~%d" % (tag, f, ln_, lo, hi))
            elif ln_ < lo or ln_ > hi:
                notes.append("%s %s 字数 %d，略偏离要求 %d~%d" % (tag, f, ln_, lo, hi))

    # --- 8 条句式是否雷同（开头 4 字撞车 ≥3 次就算是套模板）---
    opens = {}
    for r in rows:
        d = (r.get("description") or "").strip()
        if len(d) >= 4:
            opens.setdefault(d[:4], []).append(r.get("station_id"))
    same = {k: v for k, v in opens.items() if len(v) >= 3}
    if same:
        problems.append("★ 多条文案开头雷同（像套模板）：%s"
                        % "；".join("%s×%d" % (k, len(v)) for k, v in same.items()))
    return problems, notes


def rehearse_import(rows, data_dir: Path, verbose=False):
    """在临时副本上真跑一次导入，返回 (报告行列表, 是否有问题)。"""
    import core.data_manager as dm_mod

    tmp = Path(tempfile.mkdtemp(prefix="wbrehearse_"))
    try:
        for name in ("stations.json", "lines.json", "schema.json"):
            src = data_dir / name
            if src.exists():
                shutil.copy2(src, tmp / name)
        for sub in ("covers",):
            if (data_dir / sub).is_dir():
                shutil.copytree(data_dir / sub, tmp / sub, dirs_exist_ok=True)

        dm_mod.DATA_DIR = tmp
        dm_mod.STATIONS_FILE = tmp / "stations.json"
        dm_mod.LINES_FILE = tmp / "lines.json"
        dm_mod._data_manager = None

        before_doc = json.loads((tmp / "stations.json").read_text(encoding="utf-8"))
        before = before_doc["stations"]
        n_before = len(before)

        dm = dm_mod.DataManager()
        res = dm.bulk_import(rows)

        after_doc = json.loads((tmp / "stations.json").read_text(encoding="utf-8"))
        after = after_doc["stations"]
        n_after = len(after)

        lines: list[str] = []
        bad = False
        lines.append("导入前站点数 : %d" % n_before)
        lines.append("导入后站点数 : %d" % n_after)
        lines.append("新增 %d / 更新 %d / 失败 %d"
                     % (res["added"], res["updated"], res["failed"]))
        if n_after != n_before:
            bad = True
            lines.append("❌ 站点数变了！多出来的：%s"
                         % [x for x in after if x not in before][:10])
        if res["added"]:
            bad = True
            lines.append("❌ 有 %d 个被当成新站（station_id 写错了）" % res["added"])
        if res["failed"]:
            bad = True
            lines.append("❌ 有 %d 条导入失败" % res["failed"])

        # 本批字段确实写进去了吗
        for r in rows:
            sid = r.get("station_id")
            if sid not in after:
                bad = True
                lines.append("❌ %s 导入后不存在" % sid)
                continue
            for f in CREATIVE:
                if f in r and after[sid].get(f) != r[f]:
                    bad = True
                    lines.append("❌ %s 的 %s 没写进去" % (sid, f))

        # 其余站点必须一个字节都没动
        touched = {r.get("station_id") for r in rows}
        diffs = []
        for sid, old in before.items():
            if sid in touched:
                continue
            if after.get(sid) != old:
                diffs.append(sid)
        if diffs:
            bad = True
            lines.append("❌ 有 %d 个**不该被改**的站点被动过了：%s"
                         % (len(diffs), diffs[:10]))
        else:
            lines.append("✅ 其余 %d 个站点分毫未动"
                         % (n_before - len(touched & set(before))))
        return lines, bad
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="校验 AI 回传的站点文案 JSON")
    ap.add_argument("--reply", help="AI 回传的 JSON 文件")
    ap.add_argument("--reply-dir", help="装着一堆回复的目录（全部校验）")
    ap.add_argument("--batch", help="对应的批次 txt（用来核对 station_id 集合）")
    ap.add_argument("--data-dir", default=str(SRC.parent / "软件" / "data"))
    ap.add_argument("--rehearse", action="store_true",
                    help="在临时副本上真跑一次导入（不碰真实数据）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    real = None
    data_dir = Path(args.data_dir)
    try:
        real = json.loads((data_dir / "stations.json").read_text(encoding="utf-8"))["stations"]
    except Exception as e:
        print("!! 读不到真实数据（%s）：%s" % (data_dir, e))

    if args.reply_dir:
        replies = sorted(Path(args.reply_dir).glob("*.json"))
        if not replies:
            print("!! 目录里没有 .json：%s" % args.reply_dir)
            return 2
    elif args.reply:
        replies = [Path(args.reply)]
    else:
        ap.error("要给 --reply 或 --reply-dir")

    total_bad = 0
    for rp in replies:
        print("=" * 70)
        print("校验 %s" % rp.name)
        print("=" * 70)
        obj, err = load_reply(rp)
        if obj is None:
            print("❌ 解析失败：%s" % err)
            print("   （常见原因：套了 ```json 围栏、前后混了说明文字、被截断了）")
            total_bad += 1
            continue
        rows = extract_rows(obj)
        if not rows:
            print("❌ 结构不认识：既不是 {\"stations\": [...]} 也不是 [{...}]")
            total_bad += 1
            continue
        print("解析成功，共 %d 条" % len(rows))

        batch_ids = None
        if args.batch:
            batch_ids = extract_batch_ids(Path(args.batch))
            if batch_ids is None:
                print("!! 批次文件里没找到可解析的骨架，跳过 id 核对：%s" % args.batch)
        problems, notes = check_content(rows, batch_ids, real)

        print("-" * 70)
        if problems:
            print("问题 %d 条：" % len(problems))
            for p in problems:
                print("   ❌ %s" % p)
            total_bad += 1
        else:
            print("问题 0 条 ✅")
        if notes:
            print("提示 %d 条：" % len(notes))
            for n in (notes if args.verbose else notes[:10]):
                print("   · %s" % n)
            if not args.verbose and len(notes) > 10:
                print("   …（还有 %d 条，-v 看全部）" % (len(notes) - 10))

        if args.rehearse:
            # ★ 就算内容检查已经报了问题，也照样试一遍。
            #   理由：试导入给出的"站点数会不会变多"是最硬的一条证据，
            #   恰恰在最需要它的时候（id 写错）不能缺席。
            print("-" * 70)
            print("临时副本上试导入（不碰真实数据）…")
            lines, bad = rehearse_import(rows, data_dir, args.verbose)
            for ln in lines:
                print("   " + ln)
            if bad:
                total_bad += 1

    print("=" * 70)
    if total_bad:
        print("结论：%d 个文件有问题 ❌ —— 把上面列出的问题原样发回给那个 AI 让它改。" % total_bad)
    else:
        print("结论：全部通过 ✅ 可以用软件的「批量导入」导入了。")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
