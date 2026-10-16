"""v2.3 数据增补：把原图里缺失的 6 号线支线 / 有轨电车 / 坪山云巴 全部补进去。

来源：原图右下角两张附图（有轨电车线路图、坪山云巴线路图）+ 主图走廊测量。

- 6 号线支线：主图上有标记，坐标来自标记检测（精确）
- 有轨电车 主线/支线：主图只画了 4 个标记（清湖/大和/新澜/下围），
  其余站按"沿走廊等距布点"摆放（见 tools/place_along_corridor.py）
- 坪山云巴：主图只画了 首末 2 个标记，其余按折线等距摆放
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
ST = DATA / "stations.json"
LN = DATA / "lines.json"

NEW_TEMPLATE = {
    "open_date": "", "description": "", "exits": "",
    "facilities": "", "landmarks": "", "notes": "",
}


def mk(sid, lines, x, y, transfer=False, ttype=None, notes=""):
    d = dict(NEW_TEMPLATE)
    d.update({
        "station_id": sid, "station_name": sid, "lines": lines,
        "x": round(float(x), 1), "y": round(float(y), 1),
        "is_transfer": bool(transfer),
    })
    if ttype:
        d["transfer_type"] = ttype
    if notes:
        d["notes"] = notes
    return d


# ---------------- 新增站点 ----------------
NEW_STATIONS = [
    # === 6 号线支线（主图有权威标记）===
    mk("虹桥公园", ["6支"], 2813.0, 1817.5),
    mk("碧眼", ["6支"], 2810.5, 1589.5),
    mk("圳美", ["6支"], 2807.0, 1109.5),
    mk("中大", ["6支"], 2920.0, 921.0),
    mk("深理工", ["6支"], 3068.5, 773.0, notes="6号线支线北端终点"),

    # === 有轨电车 主线 ===
    mk("清龙", ["有轨电车"], 3160.2, 2982.2),
    mk("清湖学校", ["有轨电车"], 3251.9, 2986.1),
    mk("梅龙北", ["有轨电车"], 3331.5, 2906.5),
    mk("碧澜", ["有轨电车"], 3411.0, 2827.0),
    mk("文澜", ["有轨电车"], 3490.6, 2747.4),
    mk("大和", ["有轨电车", "有轨电车支线"], 3574.5, 2687.5, transfer=True,
       notes="有轨电车主线与下围支线的分岔站"),
    mk("世纪广场", ["有轨电车"], 3595.4, 2642.6),
    mk("锦鲤", ["有轨电车"], 3637.1, 2600.9),
    mk("河西", ["有轨电车"], 3678.8, 2559.2),
    mk("观城", ["有轨电车"], 3720.4, 2517.6),
    mk("大布头", ["有轨电车"], 3754.4, 2471.0),
    mk("河东", ["有轨电车"], 3726.0, 2422.0),
    mk("石角头", ["有轨电车"], 3684.3, 2380.3),
    mk("新澜", ["有轨电车"], 3661.0, 2335.0, ttype="out",
       notes="出闸换乘：距4号线观澜站约50米"),

    # === 有轨电车 下围支线 ===
    mk("东庵", ["有轨电车支线"], 3633.0, 2675.0),
    mk("高新区西", ["有轨电车支线"], 3699.9, 2675.0),
    mk("高新区", ["有轨电车支线"], 3766.9, 2675.0),
    mk("高新区东", ["有轨电车支线"], 3833.8, 2675.0),
    mk("下围", ["有轨电车支线"], 3897.5, 2689.0, notes="有轨电车下围支线终点"),

    # === 坪山云巴 ===
    mk("坪山高铁站", ["坪山云巴"], 6779.5, 2685.5, ttype="out",
       notes="出闸换乘：距16号线约100米"),
    mk("站前路东", ["坪山云巴"], 6894.6, 2684.5),
    mk("文化聚落", ["坪山云巴"], 7009.6, 2684.5),
    mk("坪山中心", ["坪山云巴"], 7124.7, 2684.7, ttype="out",
       notes="出闸换乘：距14号线约500米"),
    mk("中芯国际", ["坪山云巴"], 7230.9, 2714.6),
    mk("综合保税区", ["坪山云巴"], 7256.9, 2820.6),
    mk("燕子岭", ["坪山云巴"], 7209.1, 2918.3),
    mk("未来城", ["坪山云巴"], 7131.2, 3002.1, ttype="out",
       notes="出闸换乘：距14号线约450米"),
    mk("自然博物馆西", ["坪山云巴"], 7118.0, 3113.9),
    mk("龙背", ["坪山云巴"], 7115.5, 3229.0, ttype="out",
       notes="出闸换乘：距16号线约450米"),
    mk("比亚迪北", ["坪山云巴"], 7113.5, 3344.0, notes="坪山云巴南端终点"),
]

# ---------------- 线路定义 ----------------
NEW_LINES = [
    {
        "id": "6支", "name": "6号线支线", "color": "#008A80",
        "stations": ["光明城", "虹桥公园", "碧眼", "光明", "圳美", "中大", "深理工"],
    },
    {
        "id": "有轨电车", "name": "有轨电车", "color": "#B6B6B7",
        "stations": ["清湖", "清龙", "清湖学校", "梅龙北", "碧澜", "文澜", "大和",
                     "世纪广场", "锦鲤", "河西", "观城", "大布头", "河东", "石角头", "新澜"],
    },
    {
        "id": "有轨电车支线", "name": "有轨电车支线", "color": "#B6B6B7",
        "stations": ["大和", "东庵", "高新区西", "高新区", "高新区东", "下围"],
    },
    {
        "id": "坪山云巴", "name": "坪山云巴", "color": "#B6B6B7",
        "stations": ["坪山高铁站", "站前路东", "文化聚落", "坪山中心", "中芯国际",
                     "综合保税区", "燕子岭", "未来城", "自然博物馆西", "龙背", "比亚迪北"],
    },
]

# ---------------- 坐标/归属修正 ----------------
FIX = {
    # 光明：原坐标 (2807,1110) 实际是「圳美」的标记，导致 6 号线穿到隔壁站
    "光明": {"x": 2780.5, "y": 1352.5, "lines": ["6", "6支"], "is_transfer": True},
    # 光明城：主图上通过它的是 6 号线支线与 13 号线，6 号线主线并不经过
    "光明城": {"lines": ["6支", "13"]},
    # 清湖：4 号线与有轨电车同名两站，合并为一站并标为出闸换乘
    "清湖": {"lines": ["4", "有轨电车"], "is_transfer": True, "transfer_type": "out",
             "notes": "出闸换乘：有轨电车清湖站距4号线清湖站约50米"},
    # 石岩：原坐标 (2230.5,2483.5) 其实是「上屋」的标记；真正的石岩在 13 号线上
    "石岩": {"x": 2053.0, "y": 2665.0, "lines": ["13"], "is_transfer": False},
    # 上屋：原坐标 (2394.5,2319.5) 其实是「红坳公园」的标记
    "上屋": {"x": 2227.0, "y": 2484.0, "lines": ["6", "13"], "is_transfer": True},
    # 官田：只有 6 号线经过（13 号线走 上屋->石岩 那一支）
    "官田": {"lines": ["6"], "is_transfer": False},
}

# 完整站序修正（南→北 / 西→东，与原图一致）
SEQ_FIX = {
    "6": ["松岗", "溪头", "松岗公园", "薯田埔", "合水口", "公明广场", "红花山", "楼村",
          "科学公园", "光明", "光明大街", "凤凰城", "长圳", "上屋", "官田", "阳台山东",
          "元芬", "龙华", "红山", "深圳北", "梅林关", "翰岭", "银湖", "八卦岭",
          "体育中心", "通新岭", "科学馆"],
    "13": ["深大南", "南光", "南山书城", "人才公园", "后海", "深圳湾口岸", "科苑",
           "粤海门", "高新南", "留仙洞", "百旺", "应人石", "罗租", "石岩", "上屋",
           "红坳公园", "光明城", "德雅路", "凤凰城", "月亮路", "将围", "新庄",
           "公明广场", "上村", "下村", "李松蓢"],
}


def main():
    apply = "--apply" in sys.argv
    st = json.loads(ST.read_text(encoding="utf-8"))
    ln = json.loads(LN.read_text(encoding="utf-8"))
    S = st["stations"]

    added, fixed = [], []

    for s in NEW_STATIONS:
        sid = s["station_id"]
        if sid in S:
            print(f"  [已存在] {sid} —— 跳过新增，仅合并线路 {s['lines']}")
            old = S[sid]
            for l in s["lines"]:
                if l not in old.get("lines", []):
                    old.setdefault("lines", []).append(l)
            if s.get("transfer_type"):
                old["transfer_type"] = s["transfer_type"]
            continue
        S[sid] = s
        added.append(sid)

    for sid, patch in FIX.items():
        if sid.startswith("_"):
            continue
        if sid not in S:
            print(f"  !! {sid} 不在站表里，无法修正")
            continue
        old = dict(S[sid])
        S[sid].update(patch)
        fixed.append((sid, old, dict(S[sid])))

    # 应用完整站序修正
    L = ln["lines"]
    for lid, seq in SEQ_FIX.items():
        tgt = next((x for x in L if x["id"] == lid), None)
        if tgt is None:
            continue
        old_n = len(tgt["stations"])
        tgt["stations"] = list(seq)
        print(f"  [{lid}号线站序] {old_n} -> {len(seq)} 站")
        print(f"      {' → '.join(seq)}")

    # 上屋 / 红坳公园 需要补入站表
    for sid, lnlist, x, y, tr in (("上屋", ["6", "13"], 2227.0, 2484.0, True),
                                  ("红坳公园", ["13"], 2392.0, 2319.0, False)):
        if sid not in S:
            S[sid] = mk(sid, lnlist, x, y, transfer=tr)
            added.append(sid)

    # 公明广场：图上它是 6 号线与 13 号线的换乘胶囊
    if "公明广场" in S:
        S["公明广场"]["lines"] = ["6", "13"]
        S["公明广场"]["is_transfer"] = True

    # 追加新线路
    for nl in NEW_LINES:
        if any(x["id"] == nl["id"] for x in L):
            print(f"  [线路已存在] {nl['id']}")
            continue
        L.append(nl)

    print(f"\n新增站点 {len(added)} 个：{'、'.join(added)}")
    print(f"修正站点 {len(fixed)} 个")
    print(f"总站点 {len(S)}，总线路 {len(L)}")

    if not apply:
        print("\n（未加 --apply，仅预演）")
        return

    ts = datetime.now().strftime("%m%d%H%M")
    for f in (ST, LN):
        shutil.copy2(f, f.with_suffix(f.suffix + f".bak_v23_{ts}"))
    ST.write_text(json.dumps({"version": "2.3",
                              "description": "站点数据。x/y 为原图像素坐标（原图 8000x8000）。"
                                             " transfer_type=out 表示出闸换乘。",
                              "stations": S}, ensure_ascii=False, indent=1), encoding="utf-8")
    LN.write_text(json.dumps({"version": "2.3",
                              "description": "线路数据。stations 为按顺序排列的站名。",
                              "lines": L}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[OK] 已写回 stations.json / lines.json（备份 .bak_v23_{ts}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
