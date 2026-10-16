"""
tools/fix_line_topology.py
==========================
v2.6.18：按官方图纸（assets/shenzhen_metro.png）修复 9 处线路连接（拓扑）错误。

每一处都已在官方原图上裁图亲眼核对过（核对过程见 logs/_audit_*.png）：

  ① 5号线  删掉【宝安】（宝安只是 11号线的站；官方 5号线 宝华→宝安中心 直连）
  ② 5号线  补上西延段：黄贝岭 → 湖贝 → 东门 → 大剧院
            （官方图紫线带「5」编号直达大剧院；东门是全网缺失的站，新建）
  ③ 12号线 删掉【会展城】（会展城只是 20号线的站；官方 12号线 国展北→海上田园南 直连）
  ④ 13号线 【深大南】→【深大】（官方 粤海门→深大→高新中；深大南只是 9号线的站）
  ⑤ 13号线 【西丽】→【西丽高铁站】（官方 13号线不到 5/7号线的西丽，
            而是自己的「西丽高铁站」：高新北→西丽高铁站→石鼓→留仙洞；该站新建）
  ⑥ 7号线  补上【西丽】（官方 西丽湖→西丽→茶光；西丽是 5/7 换乘）
  ⑦ 11号线 删掉【机场东】（官方 11号线 机场北→碧海湾 直连；机场东是 1/12号线的站）
  ⑧ 坪山云巴 删掉【坪山中心】（官方图上云巴灰线在坪山中心没有设站，从旁边绕过；
            坪山中心仍是 14号线站。★ 现实中云巴有这站 —— 按用户「完全遵照官方图」处理）
  ⑨ 14号线 补上【坪山围】（官方：锦龙→坪山围→坪山广场；坪山围是 14×16 换乘，
            它的时刻表里本来就有 14号线数据 —— 纯属线路数组漏登）

同步维护 stations.json 里每站的 `lines` / `is_transfer` 字段（渲染靠它们画换乘圆点）。

★ 铁律：先备份、只改该改的、自检不过绝不落盘。
用法：
    python tools/fix_line_topology.py          # 只演练 + 自检，不写文件
    python tools/fix_line_topology.py --apply  # 备份后落盘
"""

import json
import shutil
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS = SRC_ROOT / "data" / "stations.json"
LINES = SRC_ROOT / "data" / "lines.json"

# ---------------------------------------------------------------- 修复规则
# (线路id, 动作, 参数)
REMOVE = [("5", "宝安"), ("12", "会展城"), ("11", "机场东"), ("坪山云巴", "坪山中心")]
REPLACE = [("13", "深大南", "深大"), ("13", "西丽", "西丽高铁站")]
INSERT_AFTER = [("7", "西丽湖", ["西丽"]), ("5", "黄贝岭", ["湖贝", "东门", "大剧院"]),
                ("14", "锦龙", ["坪山围"])]

# 站点 lines 字段的定案值（修复后）
LINES_OF = {
    "宝安": ["11"],
    "会展城": ["20"],
    "机场东": ["1", "12"],
    "坪山中心": ["14"],
    "深大南": ["9"],
    "深大": ["1", "13"],
    "西丽": ["5", "7"],
    "湖贝": ["2", "5"],
    "大剧院": ["1", "2", "5"],
    "东门": ["5"],
    "西丽高铁站": ["13"],
    "坪山围": ["14", "16"],
}

# 新站的初始坐标 = 在两个相邻站之间按官方图纸比例插值（重排时会再精调）
# (新站, 邻站A, 邻站B, t)  t 来自官方图上的相对位置
NEW_STATIONS = [
    ("东门", "湖贝", "大剧院", 0.62),        # 官方：湖贝(4757)…东门(4570)…大剧院(4455)
    ("西丽高铁站", "高新北", "石鼓", 0.50),  # 官方：高新北(4859)…西丽高铁站(4577)…石鼓(4293)
]

EXPECTED_COUNT = {"5": 37, "12": 37, "13": 29, "7": 28, "11": 21, "坪山云巴": 10, "14": 18}
EXPECTED_TOTAL = 381  # 379 + 东门 + 西丽高铁站

# 修复后必须成立的邻接关系（a 的下一站必须是 b）
ADJACENT = [
    ("5", "宝华", "宝安中心"), ("5", "黄贝岭", "湖贝"), ("5", "湖贝", "东门"),
    ("5", "东门", "大剧院"),
    ("12", "国展北", "海上田园南"),
    ("13", "粤海门", "深大"), ("13", "深大", "高新中"),
    ("13", "高新北", "西丽高铁站"), ("13", "西丽高铁站", "石鼓"),
    ("7", "西丽湖", "西丽"), ("7", "西丽", "茶光"),
    ("11", "机场北", "碧海湾"),
    ("坪山云巴", "文化聚落", "中芯国际"),
    ("14", "锦龙", "坪山围"), ("14", "坪山围", "坪山广场"),
]
# 修复后这些站必须不在这些线里
NOT_IN = [
    ("5", "宝安"), ("12", "会展城"), ("11", "机场东"), ("坪山云巴", "坪山中心"),
    ("13", "深大南"), ("13", "西丽"),
]


def load():
    with open(STATIONS, "r", encoding="utf-8") as f:
        sdoc = json.load(f)
    with open(LINES, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return sdoc, sdoc["stations"], doc


def apply_fixes(st, doc, now):
    logs = []
    seqs = {L["id"]: L["stations"] for L in doc["lines"]}

    # ★ 全部动作幂等：已是目标状态就跳过（允许在部分修过的数据上重跑）
    for lid, name in REMOVE:
        seq = seqs[lid]
        if name not in seq:
            logs.append(f"  {lid}号线 删除 {name}（已是目标状态，跳过）")
            continue
        seq.remove(name)
        logs.append(f"  {lid}号线 删除 {name}")

    for lid, old, new in REPLACE:
        seq = seqs[lid]
        if old not in seq:
            assert new in seq, f"{lid}号线 {old}、{new} 都找不到（数据异常）"
            logs.append(f"  {lid}号线 {old} → {new}（已是目标状态，跳过）")
            continue
        i = seq.index(old)
        seq[i] = new
        logs.append(f"  {lid}号线 {old} → {new}（第 {i + 1} 位）")

    for lid, anchor, names in INSERT_AFTER:
        seq = seqs[lid]
        i = seq.index(anchor)
        if seq[i + 1:i + 1 + len(names)] == names:
            logs.append(f"  {lid}号线 {anchor} 之后插入 {'、'.join(names)}（已是目标状态，跳过）")
            continue
        for n in names:  # 防半吊子状态：先清掉散落的同名站
            while n in seq:
                seq.remove(n)
        i = seq.index(anchor)
        seq[i + 1:i + 1] = names
        logs.append(f"  {lid}号线 {anchor} 之后插入 {'、'.join(names)}")

    # 新站记录
    for name, a, b, t in NEW_STATIONS:
        if name in st:
            logs.append(f"  新建站点 {name}（已存在，跳过）")
            continue
        sa, sb = st[a], st[b]
        st[name] = {
            "station_id": name,
            "station_name": name,
            "lines": list(LINES_OF[name]),
            "x": round(sa["x"] + (sb["x"] - sa["x"]) * t, 2),
            "y": round(sa["y"] + (sb["y"] - sa["y"]) * t, 2),
            "is_transfer": False,
            "open_date": "",
            "description": "",
            "exits": "",
            "facilities": "",
            "landmarks": "",
            "notes": "",
            "_updated_at": now,
            "timetable": "",
            "bus_transfer": "",
        }
        logs.append(f"  新建站点 {name}（{a}—{b} 之间 t={t}）")

    # 站点 lines / is_transfer 定案
    for name, lines in LINES_OF.items():
        assert name in st, f"{name} 不在 stations.json"
        st[name]["lines"] = list(lines)
        st[name]["is_transfer"] = len(lines) > 1
    logs.append(f"  同步 {len(LINES_OF)} 站的 lines/is_transfer 字段")
    return logs


def verify(st, doc):
    """双向一致性 + 定案断言。任何一条不过都抛异常（绝不带病落盘）。"""
    errs = []
    seqs = {L["id"]: L["stations"] for L in doc["lines"]}

    # 1) 数量
    for lid, n in EXPECTED_COUNT.items():
        if len(seqs[lid]) != n:
            errs.append(f"{lid}号线站数 {len(seqs[lid])} ≠ 预期 {n}")
    if len(st) != EXPECTED_TOTAL:
        errs.append(f"总站数 {len(st)} ≠ 预期 {EXPECTED_TOTAL}")

    # 2) 每条线的站都存在、无重复
    for lid, seq in seqs.items():
        if len(seq) != len(set(seq)):
            errs.append(f"{lid}号线站序有重复")
        for n in seq:
            if n not in st:
                errs.append(f"{lid}号线的 {n} 不在 stations.json")

    # 3) 双向一致：线里有站 ⇔ 站的 lines 里有线
    for lid, seq in seqs.items():
        for n in seq:
            if n in st and lid not in (st[n].get("lines") or []):
                errs.append(f"{n} 在 {lid}号线里，但它的 lines={st[n].get('lines')}")
    for n, s in st.items():
        for lid in (s.get("lines") or []):
            if lid not in seqs:
                errs.append(f"{n} 声称属于不存在的线路 {lid}")
            elif n not in seqs[lid]:
                errs.append(f"{n} 声称属于 {lid}号线，但线里没有它")

    # 4) is_transfer 与 lines 数一致
    for n, s in st.items():
        want = len(s.get("lines") or []) > 1
        if bool(s.get("is_transfer")) != want:
            errs.append(f"{n} is_transfer={s.get('is_transfer')} 与 lines={s.get('lines')} 不符")

    # 5) 定案邻接 / 排除
    for lid, a, b in ADJACENT:
        seq = seqs[lid]
        ok = any(seq[i] == a and seq[i + 1] == b for i in range(len(seq) - 1))
        if not ok:
            errs.append(f"{lid}号线里 {a}→{b} 不相邻")
    for lid, n in NOT_IN:
        if n in seqs[lid]:
            errs.append(f"{n} 不该在 {lid}号线里")
    return errs


def main():
    apply = "--apply" in sys.argv
    sdoc, st, doc = load()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    logs = apply_fixes(st, doc, now)
    print("修复动作：")
    for s in logs:
        print(s)

    errs = verify(st, doc)
    if errs:
        print(f"\n[FAIL] 自检 {len(errs)} 条不过，未落盘：")
        for e in errs:
            print("  ✗", e)
        return 1
    print("\n[OK] 自检全部通过（数量/双向一致/换乘标记/邻接/排除）")

    if not apply:
        print("（演练模式，未写文件；加 --apply 落盘）")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    for p in (STATIONS, LINES):
        bak = p.with_suffix(p.suffix + f".bak_topo_{ts}")
        shutil.copy2(p, bak)
        print(f"  备份 {p.name} → {bak.name}")
    with open(STATIONS, "w", encoding="utf-8") as f:
        json.dump(sdoc, f, ensure_ascii=False, indent=2)
    with open(LINES, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已落盘：{STATIONS.name}（{len(st)} 站）、{LINES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
