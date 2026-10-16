# -*- coding: utf-8 -*-
"""make_station_copy_batches.py —— 生成"站点文案补全"的批次文件（给外部 AI 用）。

为什么要有它：
  379 个站点要补写"简介 / 周边地标 / 备注 / 设施"这类文字，一次全丢给 AI 会
  因为上下文太长而掉质量。所以按 **每批 8 个站点** 切成若干 txt，一个 txt 发一次，
  每个 txt **自带完整的写作标准**（不用另外附带说明，避免用户漏发）。

设计要点（都是踩过/想清楚才这么定的）：
  1. ★ **只写"描述性"字段，不碰"事实"字段**。
     description / landmarks / notes / facilities 允许在公认常识范围内发挥；
     而 `exits`（出入口）和 `open_date`（开通日期）是**可核查的事实**——
     AI 编出来的"A 出口在某路"就是假信息。所以默认不放进 JSON 骨架
     （骨架里没有的键，AI 就不会去写）。要改：--extra-fields exits,open_date
  2. ★ **line 上前后站**要一起给。AI 知道"上一站/下一站是谁"才能写得像本地人；
     而且批次按**沿线顺序**切，同一批站点天然在同一个片区，文案不会互相打架。
  3. ★ **参考信息放在 JSON 外面**。如果把 lines / is_transfer 也塞进 JSON，
     导入时会被当成"要写入的值"把线路覆盖掉（upsert 是合并写入）。
     所以表格归表格、骨架归骨架。
  4. ★ 要求回传 `{"stations": [...]}` 这种形状 —— 软件里的「批量导入」正好认它
     （main_window._on_import → DataManager.bulk_import），不用手工一条条粘贴。
  5. ★ station_id 必须原样返回：bulk_import 里
     `sid = row.get("station_id") or 生成新ID` → 缺了或改了就会**新建站点**
     （我们刚清掉的那个"新站点"垃圾就是这么来的）。

用法：
    python tools/make_station_copy_batches.py                    # 默认每批 8 个
    python tools/make_station_copy_batches.py --batch 6
    python tools/make_station_copy_batches.py --data-dir ..\\软件\\data
    python tools/make_station_copy_batches.py --out-dir 站点文案
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# 参与生成的"描述性"字段（顺序 = 出现在 JSON 骨架里的顺序）
CREATIVE = [
    ("description", "简介", "60~110 字", "必填"),
    ("landmarks", "周边地标", "20~40 字", "必填"),
    ("notes", "备注", "20~40 字", "建议填"),
    ("facilities", "设施", "0~25 字，拿不准就填 \"\"", "可留空"),
]
# 默认**不**生成的"事实"字段（要开就 --extra-fields）
FACTUAL = ["exits", "open_date"]


# ---------------------------------------------------------------- 标准正文
STANDARD = """\
================================================================================
《深圳地铁示意图 · 站点文案标准》v1.0
================================================================================

【你要做什么】
为下面 8 个地铁站点，各写 4 段中文短文案，然后**只返回一个 JSON**。

【写进哪里 / 给谁看】
深圳地铁示意图软件的站点资料卡里。用户点开一个站点就能看到这几栏：
    简介 / 出入口信息 / 设施（电梯·卫生间等）/ 周边地标 / 备注 / 开通日期

【★ 只写这 4 栏，另外 2 栏不许碰】
本批只写：description（简介）、landmarks（周边地标）、notes（备注）、facilities（设施）。
**不要动** 出入口信息（exits）和 开通日期（open_date）—— 它们是可核查的事实
（哪个出口在哪条路、哪天开通），凭印象写就是假信息。本批的 JSON 骨架里
也没有这两项，请勿自行添加。

【角度：偏 经商 / 创业 / 旅游】
不要三个角度平均用力。**每个站点挑最贴的 1~2 个角度**来写：
  · 经商视角 —— 这一带是哪种商业形态：核心商圈 / 写字楼办公区 / 产业园区 /
    电子或批发市场 / 老社区生活配套 / 交通枢纽型商业；人流结构是什么
    （工作日通勤、商务差旅、周末家庭、口岸或景区游客）。
  · 创业视角 —— 适合哪一类业态落地、客群的消费场景是什么。
    ★ 只写"适合哪一类"，不要写具体店名，也不要写租金、客流、营业额等数字。
  · 旅游视角 —— 有没有值得为它下车的地方（公园、古迹、老街、观景带、
    展览馆、城市记忆点）。
允许三种角度在一次文案里自然混合，但**必须贴合该站给出的线路与相邻站**，
不要写成"所有地铁站都适用"的废话。

--------------------------------------------------------------------------------
每个字段怎么写（字数按中文字符算，标点也算）
--------------------------------------------------------------------------------

■ description（简介）  {n1}
  三句话的骨架：①位置与线路（**只用**给定的线路信息，不要自己加线路）；
  ②这一带是什么地方（用地形态 + 人群结构）；③一个值得注意的角度
  （商业形态 / 创业气质 / 城市记忆里的一句话）。
  ✓ 正例：位于南山中心区北侧，1 号线沿线。周边以科技园办公和成熟住宅区为主，
    工作日通勤客流大、午间餐饮需求集中，是典型的职住混合型站点。
  ✗ 反例：深圳必打卡的绝佳地段，周边美食数不胜数，创业者的天堂！（营销腔、无信息）

■ landmarks（周边地标）  {n2}
  3~5 个公共认知度高的地标或片区类型，用顿号隔开。
  ✓ 正例：科技园、深圳湾体育中心、高新园商圈
  ✗ 反例：楼下的张记肠粉店（具体小店，不算地标）

■ notes（备注）  {n3}
  一条实用提示。换乘站优先写"换乘价值 / 方向感"（它连着哪几条线、
  去哪些片区要在这一站换）；普通站写客流或使用场景的提醒。
  ✓ 正例：与 9 号线换乘，去往梅林、下沙一带在这一站换最顺；
    工作日晚高峰出站口人流量较大。

■ facilities（设施）  {n4}
  只写"这类站点普遍都配备"的通用设施，例如：无障碍电梯、卫生间、母婴室、客服中心。
  ⚠️ 没有把握就填空字符串 ""，不要凑字。

--------------------------------------------------------------------------------
语气与禁忌（违反即作废）
--------------------------------------------------------------------------------
1. 简体中文。不要 emoji、不要 Markdown 符号、不要换行符（每段就是一句话串）。
2. 禁止营销词：绝佳、必打卡、超值、首选、火爆、天花板、不容错过…
3. 禁止预测与规划：将建成、即将开通、未来会有、规划中的…
4. 禁止**具体**信息：店名/品牌名、价格、电话、门牌号、出口编号（A/B/C 口）、
   开通日期、客流量或租金数字。
5. 同一批 8 个站点，句式要有区别 —— 8 条读起来像一个模板套出来的，就是不合格。
6. 拿不准的内容宁可不写（该字段填空字符串），也不要猜。

--------------------------------------------------------------------------------
输出格式（只输出 JSON，别的什么都不要）
--------------------------------------------------------------------------------
· 直接输出 JSON 本体：**不要** ```json 代码块围栏，不要前后加任何解释、不要加标题。
· 形状固定为：{"stations": [ …8 条… ]}
· 每条只含 6 个键，顺序照抄骨架：
      station_id、station_name、description、landmarks、notes、facilities
· ★ station_id 和 station_name **原样照抄，一个字符都不要改**
  （station_id 是数据库主键；改了或漏了，软件会当成"新建站点"，多出重复站点。）
· 骨架里所有 <FILL> 都要替换成实际文字或空字符串 ""，一个都不许留。

--------------------------------------------------------------------------------
交卷前自检 5 条
--------------------------------------------------------------------------------
1. 是不是正好 8 条？一条不多、一条不少？
2. station_id / station_name 有没有被改动？
3. 还有没有 <FILL> 没替换掉？
4. description 是否 60~110 字？有没有混进店名、价格、出口编号、日期？
5. 8 条是不是同一个句式？（是的话重写，要像不同的人写的）
"""


def load_json(p: Path):
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def build_line_index(lines_doc) -> Tuple[List[dict], Dict[str, List[Tuple[str, int, int]]]]:
    """返回 (按 order 排好的线路, {station_id: [(line_id, 位置, 该线站点数)]})."""
    lines = sorted(lines_doc.get("lines") or [], key=lambda x: x.get("order", 999))
    idx: Dict[str, List[Tuple[str, int, int]]] = {}
    for ln in lines:
        ids = [s for s in (ln.get("stations") or []) if isinstance(s, str)]
        for i, sid in enumerate(ids):
            idx.setdefault(sid, []).append((ln.get("id"), i, len(ids)))
    return lines, idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None,
                    help="数据目录（默认 ../软件/data，也就是软件真正在用的那份）")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 源码/站点文案）")
    ap.add_argument("--batch", type=int, default=8, help="每批站点数上限（默认 8）")
    ap.add_argument("--no-balance", dest="balance", action="store_false",
                    help="不做均分，直接按上限切（会产生一个很短的尾批）")
    ap.set_defaults(balance=True)
    ap.add_argument("--extra-fields", default="",
                    help="额外要生成的字段（用逗号分隔），例如 exits,open_date；默认不生成")
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve() if args.data_dir \
        else (ROOT.parent / "软件" / "data").resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir \
        else (ROOT / "站点文案").resolve()

    stations = load_json(data_dir / "stations.json")["stations"]
    lines = load_json(data_dir / "lines.json")
    line_list, line_idx = build_line_index(lines)

    extra = [f.strip() for f in args.extra_fields.split(",") if f.strip()]
    bad_extra = [f for f in extra if f not in FACTUAL]
    if bad_extra:
        print("!! --extra-fields 只支持 %s（不支持 %s）" % (FACTUAL, bad_extra))
        sys.exit(1)
    fields = list(CREATIVE) + [(k, k, "", "可选") for k in extra]

    # ---------- 站点顺序：沿线路走（同一批天然在同一片区）----------
    ordered: List[str] = []
    seen = set()
    for ln in line_list:
        for sid in (ln.get("stations") or []):
            if isinstance(sid, str) and sid in stations and sid not in seen:
                seen.add(sid)
                ordered.append(sid)
    left = [s for s in stations if s not in seen]        # 不在任何线路上的（正常应为 0）
    ordered += left

    # ---------- 切批 ----------
    n = max(1, args.batch)
    if args.balance:
        # 均分：379 个站 / 每批≤8 → 48 批 → 43 批 8 个 + 5 批 7 个。
        # 比"47 批 8 个 + 尾批 3 个"好：尾批不会只剩两三个站白跑一轮。
        nb = (len(ordered) + n - 1) // n
        base, rem = divmod(len(ordered), nb)
        batches, pos = [], 0
        for i in range(nb):
            sz = base + (1 if i < rem else 0)
            batches.append(ordered[pos:pos + sz])
            pos += sz
    else:
        batches = [ordered[i:i + n] for i in range(0, len(ordered), n)]
    assert all(len(b) <= n for b in batches), "存在超过批大小的批次"
    total = len(batches)

    out_dir.mkdir(parents=True, exist_ok=True)
    line_name = {ln.get("id"): (ln.get("name") or ln.get("id")) for ln in line_list}
    line_ord = {ln.get("id"): i for i, ln in enumerate(line_list)}

    def neighbors_text(sid: str) -> str:
        """这个站点在它每条线路上的前后站。"""
        out = []
        for lid, i, cnt in sorted(line_idx.get(sid, []), key=lambda t: line_ord.get(t[0], 999)):
            ids = [s for s in (line_ids.get(lid) or [])]
            prev_ = ids[i - 1] if i > 0 else "—（该线起点）"
            next_ = ids[i + 1] if i + 1 < cnt else "—（该线终点）"
            out.append("%s：%s → **[本站]** → %s" % (line_name.get(lid, lid), prev_, next_))
        return " ；\n      ".join(out) if out else "（该站不在任何线路的站点列表里）"

    line_ids = {ln.get("id"): [s for s in (ln.get("stations") or [])] for ln in line_list}

    # ---------- 写批次 ----------
    index_rows = []
    for bi, group in enumerate(batches, start=1):
        title = ("=" * 78
                 + "\n深圳地铁示意图 · 站点文案补全   第 %02d / %d 批（本批 %d 个站点）\n"
                 % (bi, total, len(group))
                 + "=" * 78 + "\n")
        ref = ["-" * 78,
               "本批参考信息（都是事实，照用、不要改）",
               "-" * 78]
        ref.append("  站名       线路              换乘   线路上相邻站（按线路顺序）")
        for k, sid in enumerate(group, start=1):
            d = stations[sid]
            lnames = " ".join(line_name.get(x, x) for x in (d.get("lines") or [])) or "（无）"
            ref.append("  %-10s %-16s %-5s  %s"
                       % (sid, lnames, "是" if d.get("is_transfer") else "否",
                          neighbors_text(sid)))
        ref.append("")

        skel = ['{"stations": [']
        for i, sid in enumerate(group):
            d = stations[sid]
            parts = ['{"station_id": %s' % json.dumps(sid, ensure_ascii=False),
                     '"station_name": %s' % json.dumps(d.get("station_name") or sid,
                                                       ensure_ascii=False)]
            for key, _label, _w, _req in fields:
                parts.append('"%s": "<FILL>"' % key)
            row = "  " + ", ".join(parts) + "}"          # ★ 别忘了闭合对象，否则整块不是合法 JSON
            if i < len(group) - 1:
                row += ","
            skel.append(row)
        skel.append("]}")
        skel.append("")

        body = (title
                + "\n" + STANDARD.replace("{n1}", CREATIVE[0][2]).replace("{n2}", CREATIVE[1][2])
                .replace("{n3}", CREATIVE[2][2]).replace("{n4}", CREATIVE[3][2])
                + "\n" + "\n".join(ref)
                + "=" * 78
                + "\n请把下面 JSON 里所有 <FILL> 替换掉，然后原样返回"
                  "（不要加解释、不要加代码块围栏）\n"
                + "=" * 78 + "\n"
                + "\n".join(skel))
        p = out_dir / ("批次%02d.txt" % bi)
        with io.open(p, "w", encoding="utf-8-sig") as f:
            f.write(body)
        index_rows.append("  批次%02d.txt  →  %s" % (bi, "、".join(group)))

    # ---------- 00 号：标准 + 导入说明 + 索引 ----------
    howto = """\
================================================================================
怎么用这批文件（给操作的人看）
================================================================================

0. 目录：%s
   共 %d 个批次文件（每批最多 %d 个站点，合计 %d 个站点）+ 本说明文件。

1. 把【一个批次文件】整份发给另一个 AI（一次只发一个，别合并 —— 合并了字数一多
   质量就会掉）。它会按文件里的标准返回一段 JSON。

2. 把返回的 JSON 存成一个 .json 文件。文件名随意，例如 批次01.json。
   编码不用操心：UTF-8、带 BOM 的 UTF-8、记事本那个"Unicode"(UTF-16) 都认。
   前后带了 "```json" 围栏或几句解释也没关系，下一步的脚本会自动剥掉。

3. ★ 导进软件之前，先跑一遍校验 —— 这一步能挡掉绝大多数翻车：
       cd C:\\software\\subway\\源码
       python tools\\check_ai_reply.py --reply "…\\批次01.json" --batch "站点文案\\批次01.txt" --rehearse
   它会检查：能不能解析、station_id 有没有被改动、有没有漏填 <FILL>、
   有没有踩禁忌（营销词 / 价格数字 / 出口编号 / emoji / Markdown / 换行 /
   8 条句式雷同），字数对不对。
   --rehearse 还会在**临时副本**上真跑一次导入，告诉你：
       · 站点数会不会变多（变多 = AI 把 station_id 改错了）
       · 本批的字段有没有真的写进去
       · 其余站点有没有被误动
   看到「结论：全部通过 ✅」再往下走。有问题的把它列出的那几行原样发回给 AI 让它改。

4. ★ 导入前先备份：把 软件\\data\\stations.json 复制一份留底
   （软件自己也会留一份 .bak，但多留一份更稳）。

5. 打开软件 → 工具栏「批量导入」→ 选那个 .json。
   导入是**按 station_id 合并更新**：只覆盖 description / landmarks / notes /
   facilities 这几栏，坐标、线路、站名都不受影响。
   正常会弹「新增 0 个、更新 8 个、失败 0 个」——**新增必须是 0**。

6. ★ 再看窗口右下角的「站点数」：应该还是 **%d**。
   如果变多了，说明 AI 把 station_id 改错或漏了 —— 软件当成"新建站点"了。
   这种情况别慌：关掉软件，把 软件\\data\\stations.json 用第 4 步的备份盖回去，
   然后让那个 AI 重新输出（在提示里强调"station_id 原样照抄"）。

常见小问题
 · AI 只写了 6~7 条 → 让它"补齐到 8 条，一条都不能少"。
 · 校验报「开头雷同 / 像套模板」→ 把这条要求再强调一遍重发，它会重写。
 · 校验报「里有数字」→ 多半是写了价格或客流数字，让 AI 去掉。
 · 想连「出入口信息」「开通日期」一起生成 → 说一声就能重新生成
   （但这两个是可核查的事实，AI 没有可靠来源时写出来的大概率是假的，建议不要）。

================================================================================
批次索引（共 %d 批）
================================================================================
%s
""" % (str(out_dir), total, n, len(ordered), len(ordered), total, "\n".join(index_rows))

    p0 = out_dir / "00_标准与导入说明.txt"
    with io.open(p0, "w", encoding="utf-8-sig") as f:
        f.write(howto + STANDARD.replace("{n1}", CREATIVE[0][2])
                .replace("{n2}", CREATIVE[1][2])
                .replace("{n3}", CREATIVE[2][2])
                .replace("{n4}", CREATIVE[3][2]))

    # ---------- 自检 ----------
    print("=" * 78)
    print("数据源   : %s（%d 个站点）" % (data_dir, len(stations)))
    print("输出目录 : %s" % out_dir)
    print("每批站点 : %d    批次数：%d    覆盖站点：%d"
          % (n, total, sum(len(g) for g in batches)))
    dup = len(ordered) - len(set(ordered))
    print("重复站点 : %d（应为 0）" % dup)
    print("未在任何线路上的站点：%d %s" % (len(left), left[:5]))
    over = [i + 1 for i, g in enumerate(batches) if len(g) > n]
    sizes = {}
    for g in batches:
        sizes[len(g)] = sizes.get(len(g), 0) + 1
    print("批次大小分布：%s（上限 %d）"
          % (" / ".join("%d个站 × %d 批" % (k, v) for k, v in sorted(sizes.items(),
                                                                  reverse=True)), n))
    print("超批大小的批次：%s（应为空）" % over)
    print("生成字段 : %s" % ", ".join(k for k, *_ in fields))
    print("=" * 78)
    print("准备好后把「批次01.txt」整份发给另一个 AI 即可。")
    print("（转发前可先跑一遍 tools/check_station_copy_batches.py 自检）")


if __name__ == "__main__":
    main()
