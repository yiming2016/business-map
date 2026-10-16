# -*- coding: utf-8 -*-
"""
fix_official_gaps.py —— 补掉"我们自己造成的"官网数据缺口。

==========================================================================
先分清两种"没数据"，这一点非常重要
==========================================================================
体检（`tools/_audit_pending.py`）报 33 站 timetable 为空、64 站 exits 为空。
但**绝大多数跟我们无关**，硬补就是编数据（违反铁律）：

  ① 有轨电车 / 坪山云巴（约 30 站）
     szmc.net 是**地铁**官网，压根不收录有轨电车和云巴 ⇒ 永远查不到。
  ② 4 号线北段、13 号线（34 站缺出入口）
     官网这些站的 `outAndText` 是空的、`siteIntroduce` 写着"暂无数据"
     ⇒ **上游就没给**，已实时抽查 0412(上塘) 确认。
  ③ 歌剧院、潮汐公园（13 号线新站）
     官网站点清单里**没有这两个名字** ⇒ 官网未收录。

真正是**我们自己造成**的只有 2 个，本脚本只修这 2 个：

  ④ 观澜湖 —— 官网名字是 `"观澜湖\t"`（**带一个制表符**！）
     我们库里是干净的"观澜湖"，按名字查永远落空。按**编号 0422** 查就拿到了。
  ⑤ 幛背   —— 官网是 **嶂背**（编号 1410），我们库里**写错字了**（幛≠嶂）。

==========================================================================
数据来源（2026-09-29 实时拉取，可复核）
==========================================================================
  https://www.szmc.net/zdxx?StieCode=0422   → 观澜湖
  https://www.szmc.net/zdxx?StieCode=1410   → 嶂背
  （★ GET 带 `?StieCode=` 也能查，不必 POST —— 本次实测 bash 里 POST 被
    SSL 握手挡住，改用 GET 才拿到。）

★ 只**照抄**官网返回值，一个字不编。官网写"暂无数据"的字段就让它空着。

用法：
    python tools/fix_official_gaps.py            # 只报告
    python tools/fix_official_gaps.py --apply    # 落盘（自动备份）
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATIONS = ROOT / "data" / "stations.json"
LINES = ROOT / "data" / "lines.json"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------- 官网原文

# 0422 观澜湖：三个日期类型官网给的值完全一样，照抄
TT_GUANLANHU = (
    "工作日 · 4号线：往福田口岸 首06:25 末23:02；往牛湖 首06:56 末00:05\n"
    "休息日 · 4号线：往福田口岸 首06:25 末23:02；往牛湖 首06:56 末00:05\n"
    "节假日 · 4号线：往福田口岸 首06:25 末23:02；往牛湖 首06:56 末00:05"
)
# 官网 0422 的 busInof 是「此站暂无数据」，outAndText 为空 ⇒ 出入口/公交**不填**

TT_ZHANGBEI = (
    "工作日 · 14号线：往岗厦北 首06:26 末23:24；往沙田 首06:31 末00:01\n"
    "休息日 · 14号线：往岗厦北 首06:14 末23:24；往沙田 首06:30 末00:00\n"
    "节假日 · 14号线：往岗厦北 首06:14 末00:24；往沙田 首06:30 末01:00"
)
_EX_ZB = ("嶂背郊野公园、宝荷路南侧、深圳市肿瘤医院、"
          "深圳市公安局交通警察支队龙岗大队宝荷扣车场、嶂背地铁站公交站")
EXITS_ZHANGBEI = f"A出入口：{_EX_ZB}\nB出入口：{_EX_ZB}"
BUS_ZHANGBEI = ("B出入口 · 嶂背地铁站：B867\n"
                "A出入口 · 嶂背地铁站：B867")

OLD_NAME = "幛背"      # 我们库里的错字
NEW_NAME = "嶂背"      # 官网正确写法


def main():
    apply = "--apply" in sys.argv
    sdata = json.load(open(STATIONS, encoding="utf-8"))
    st = sdata["stations"]
    ldata = json.load(open(LINES, encoding="utf-8"))

    print("=" * 70)
    print("只修「我们自己造成」的 2 个缺口（其余是上游没给，不编）")
    print("=" * 70)

    # ---------- ⑤ 改名 幛背 → 嶂背 ----------
    if OLD_NAME in st:
        v = st.pop(OLD_NAME)
        v["station_id"] = NEW_NAME
        v["station_name"] = NEW_NAME
        st[NEW_NAME] = v
        print(f"\n[改名] 站点 {OLD_NAME} → {NEW_NAME}（官网清单写作「嶂背」，我们是错字）")
        renamed_lines = 0
        for L in ldata["lines"]:
            for i, n in enumerate(L["stations"]):
                if n == OLD_NAME:
                    L["stations"][i] = NEW_NAME
                    renamed_lines += 1
                    print(f"        线路 {L['id']}（{L['name']}）站序里的站名同步改掉")
        if renamed_lines == 0:
            print("        [警告] lines.json 里没找到这个站名！")
    else:
        print(f"\n[改名] 库里已经没有「{OLD_NAME}」了，跳过")

    # ---------- 填数据 ----------
    def put(name, **kw):
        if name not in st:
            print(f"  [跳过] 库里没有「{name}」")
            return
        for k, val in kw.items():
            if val is None or (isinstance(val, str) and not val.strip()):
                continue
            st[name][k] = val
            st[name]["_updated_at"] = NOW
            print(f"  · {name}.{k} ← {val.splitlines()[0][:52]}")

    print("\n[填数据] 嶂背（编号 1410）")
    put(NEW_NAME, timetable=TT_ZHANGBEI, exits=EXITS_ZHANGBEI,
        bus_transfer=BUS_ZHANGBEI)

    print("\n[填数据] 观澜湖（编号 0422）")
    put("观澜湖", timetable=TT_GUANLANHU)
    print("  · 观澜湖的出入口/公交官网写「此站暂无数据」⇒ **留空，不编**")

    # ---------- 自检 ----------
    print("\n[自检]")
    n_st = len(st)
    tt_empty = sorted(n for n, v in st.items() if not (v.get("timetable") or "").strip())
    ex_empty = sorted(n for n, v in st.items() if not (v.get("exits") or "").strip())
    print(f"  站数 {n_st}（应为 379，改名不该增减）")
    print(f"  timetable 仍为空 {len(tt_empty)} 站")
    print(f"  exits 仍为空 {len(ex_empty)} 站")
    for L in ldata["lines"]:
        for n in L["stations"]:
            if n not in st:
                print(f"  [FAIL] lines.json 里的「{n}」在 stations.json 里不存在！")
    print(f"  嶂背 timetable 已填：{bool((st.get(NEW_NAME) or {}).get('timetable'))}")
    print(f"  观澜湖 timetable 已填：{bool((st.get('观澜湖') or {}).get('timetable'))}")

    if not apply:
        print("\n（只报告，未落盘。加 --apply 才写。）")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in (STATIONS, LINES):
        shutil.copy2(p, p.with_suffix(p.suffix + f".bak_gap_{ts}"))
    json.dump(sdata, open(STATIONS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(ldata, open(LINES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[OK] 落盘 → {STATIONS.name} / {LINES.name}")
    print(f"[OK] 备份 → *.bak_gap_{ts}")


if __name__ == "__main__":
    main()
