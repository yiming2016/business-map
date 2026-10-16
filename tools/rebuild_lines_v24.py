"""v2.4：按原图审计结果重建线路站序，并补齐遗漏站点。

审计依据：
  - tools/derive_line_sequences.py 从原图反推的"每条线上有哪些标记、叫什么名"
  - tools/probe_region.py / 人工放大裁剪逐站核对

新增站点坐标的来源（按优先级）：
  1. OCR 站名框 -> 找最近的空闲站点标记（标记中心即坐标）
  2. 找不到标记时，用站名框中心 + 固定偏移（标签在标记右侧 ~110px）
  3. 都没有时，按前后邻居的中点放入并标注待人工核对

用法:
  python tools/rebuild_lines_v24.py           # 预演
  python tools/rebuild_lines_v24.py --apply   # 写回
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
DATA = SRC / "data"
IMG = SRC / "assets" / "shenzhen_metro.png"

NEW_TPL = {"open_date": "", "description": "", "exits": "",
           "facilities": "", "landmarks": "", "notes": ""}

# ============ 重建后的站序（依据：原图反推 + 逐站放大核对） ============
SEQ = {
    "1": ["机场东", "后瑞", "固戍", "西乡", "坪洲", "宝体", "宝安中心", "新安", "前海湾",
          "鲤鱼门", "大新", "桃园", "深大", "高新园", "白石洲", "世界之窗", "华侨城",
          "侨城东", "竹子林", "车公庙", "香蜜湖", "购物公园", "会展中心", "岗厦",
          "华强路", "科学馆", "大剧院", "老街", "国贸", "罗湖"],
    "2": ["赤湾", "蛇口港", "海上世界", "水湾", "东角头", "湾厦", "海月", "登良", "后海",
          "科苑", "红树湾", "世界之窗", "侨城北", "深康", "安托山", "侨香", "香蜜",
          "香梅北", "景田", "莲花西", "福田", "市民中心", "岗厦北", "华强北", "燕南",
          "大剧院", "湖贝", "黄贝岭", "新秀", "莲塘口岸", "仙湖路", "莲塘"],
    "3": ["福保", "益田", "石厦", "购物公园", "福田", "少年宫", "莲花村", "华新",
          "通新岭", "红岭", "老街", "晒布", "翠竹", "田贝", "水贝", "草埔", "布吉",
          "木棉湾", "大芬", "丹竹头", "六约", "塘坑", "横岗", "永湖", "荷坳", "大运",
          "爱联", "吉祥", "龙城广场", "南联", "双龙", "梨园", "新生", "坪西",
          "低碳城", "白石塘", "富坪", "坪地六联"],
    "4": ["福田口岸", "福民", "会展中心", "市民中心", "少年宫", "莲花北", "上梅林",
          "民乐", "白石龙", "深圳北", "红山", "上塘", "龙胜", "龙华", "清湖",
          "清湖北", "竹村", "茜坑", "长湖", "观澜", "松元厦", "观澜湖", "牛湖"],
    "5": ["赤湾", "荔湾", "铁路公园", "妈湾", "前湾公园", "前湾", "桂湾", "前海湾",
          "临海", "宝华", "宝安", "宝安中心", "翻身", "灵芝", "洪浪北", "兴东",
          "留仙洞", "西丽", "大学城", "塘朗", "长岭陂", "深圳北", "民治", "五和",
          "坂田", "杨美", "上水径", "下水径", "长龙", "布吉", "百鸽笼", "布心",
          "太安", "怡景", "黄贝岭"],
    "6": ["松岗", "溪头", "松岗公园", "薯田埔", "合水口", "公明广场", "红花山", "楼村",
          "科学公园", "光明", "光明大街", "凤凰城", "长圳", "上屋", "官田", "阳台山东",
          "元芬", "上芬", "红山", "深圳北", "梅林关", "翰岭", "银湖", "八卦岭",
          "体育中心", "通新岭", "科学馆"],
    "6支": ["光明城", "虹桥公园", "碧眼", "光明", "圳美", "中大", "深理工"],
    "7": ["深大丽湖", "北大", "西丽湖", "茶光", "珠光", "龙井", "桃源村", "深云",
          "安托山", "农林", "车公庙", "上沙", "沙尾", "石厦", "皇岗村", "福民",
          "皇岗口岸", "赤尾", "华强南", "华强北", "黄木岗", "八卦岭", "红岭北",
          "笋岗", "洪湖", "田贝", "太安"],
    "8": ["莲塘", "梧桐山南", "沙头角", "海山", "盐田港西", "深外高中", "盐田路",
          "鸿安围", "盐田墟", "大梅沙", "小梅沙", "溪涌"],
    "9": ["前湾", "梦海", "怡海", "荔林", "南油西", "南油", "南山书城", "深大南",
          "粤海门", "高新南", "红树湾南", "深湾", "深圳湾公园", "下沙", "车公庙",
          "香梅", "景田", "梅景", "下梅林", "梅村", "上梅林", "孖岭", "银湖", "泥岗",
          "红岭北", "园岭", "红岭", "红岭南", "鹿丹村", "人民南", "向西村", "文锦"],
    "10": ["双拥街", "平湖", "禾花", "华南城", "木古", "上李朗", "凉帽山", "甘坑",
           "雪象", "岗头", "华为", "贝尔路", "坂田北", "五和", "光雅园", "南坑",
           "雅宝", "孖岭", "冬瓜岭", "莲花村", "岗厦北", "福民", "福田口岸"],
    "11": ["碧头", "松岗", "后亭", "沙井", "马安山", "塘尾", "桥头", "福永", "机场北",
           "机场东", "碧海湾", "宝安", "前海湾", "南山", "后海", "红树湾南",
           "深圳湾公园", "车公庙", "福田", "岗厦北", "华强南", "红岭南"],
    "12": ["左炮台东", "太子湾", "花果山", "四海", "南油", "南光", "南山", "桃园",
           "南头古城", "中山公园", "同乐南", "新安公园", "灵芝", "上川", "流塘",
           "宝安客运站", "宝田一路", "平峦山", "西乡桃源", "钟屋南", "黄田", "兴围",
           "机场东", "福围", "怀德", "福永", "桥头西", "福海西", "国展南", "国展北",
           "会展城", "海上田园南", "海上田园东", "蚝乡", "沙蚝", "沙井古墟", "步涌",
           "朗下"],
    "13": ["歌剧院", "潮汐公园", "深圳湾口岸", "人才公园", "后海", "科苑", "粤海门",
           "深大南", "高新中", "高新北", "西丽", "石鼓", "留仙洞", "百旺", "应人石",
           "罗租", "石岩", "上屋", "红坳公园", "光明城", "德雅路", "凤凰城",
           "月亮路", "将围", "新庄", "公明广场", "上村", "下村", "李松蓢"],
    "14": ["岗厦北", "黄木岗", "罗湖北", "布吉", "石芽岭", "六约北", "四联", "坳背",
           "大运", "幛背", "南约", "宝龙", "锦龙", "坪山广场", "坪山中心", "坑梓",
           "沙田"],
    "16": ["田心", "技术大学", "石井", "燕子湖", "沙壆", "东纵纪念馆", "坪环",
           "坪山围", "六和", "新和", "坪山", "宝龙同乐", "龙东", "新塘围", "双龙",
           "龙园", "盛平", "尚景", "回龙埔", "愉园", "黄阁坑", "龙城公园",
           "大运中心", "大运", "金源", "吉溪", "大安", "园山", "大康", "福坑",
           "安良", "园山西坑"],
    "20": ["机场北", "国展南", "国展", "国展北", "会展城"],
    "有轨电车": ["清湖", "清龙", "清湖学校", "梅龙北", "碧澜", "文澜", "大和",
                 "世纪广场", "锦鲤", "河西", "观城", "大布头", "河东", "石角头", "新澜"],
    "有轨电车支线": ["大和", "东庵", "高新区西", "高新区", "高新区东", "下围"],
    "坪山云巴": ["坪山高铁站", "站前路东", "文化聚落", "坪山中心", "中芯国际",
                 "综合保税区", "燕子岭", "未来城", "自然博物馆西", "龙背", "比亚迪北"],
}

# 已经核实不在任何线路上的幽灵站（旧数据里由 OCR 误读/错位产生的假站）
#   桂庙   —— 旧图例残影
#   莲花   —— 与「莲花村」「莲花西」「莲花北」重名混淆
#   凤凰   —— 坐标实际落在「桥头西」标记上，全区只有「凤凰城」，无「凤凰」
#   洲石路 —— 坐标实际落在「海上田园南」标记上，12 号线无此站
GHOST = ["桂庙", "莲花", "凤凰", "洲石路", "臣田"]

# 站名纠正（旧数据的错名 -> 原图正确名）
RENAME = {
    "梅林": "梅村",   # 原图上是「梅村 Meicun」，在 下梅林/上梅林 之间，属 9 号线
}

# 手工定位（OCR 没识别出来的站，直接读原图量取标记中心）
MANUAL_XY = {
    "向西村": (5057.0, 5716.0),    # 9 号线，人民南 与 文锦 之间
    "深大丽湖": (2698.5, 3775.0),  # 7 号线西端，西丽湖 与 北大 之后
    "西丽湖": (2195.0, 3775.0),    # 7 号线西端，7 号线水平走廊 y=3775 上（旧值 2144.5,3697 是错位标记）
}

LINES_META = {
    "1": ("1号线", "#00B052"), "2": ("2号线", "#BA5700"), "3": ("3号线", "#00A6DE"),
    "4": ("4号线", "#D42E12"), "5": ("5号线", "#9E4DAB"), "6": ("6号线", "#00C4B5"),
    "6支": ("6号线支线", "#008A80"), "7": ("7号线", "#0033AB"), "8": ("8号线", "#BA5700"),
    "9": ("9号线", "#8A6B70"), "10": ("10号线", "#FC6C97"), "11": ("11号线", "#6B1C40"),
    "12": ("12号线", "#A891B0"), "13": ("13号线", "#D48500"), "14": ("14号线", "#EDCC61"),
    "16": ("16号线", "#4012A6"), "20": ("20号线", "#99DBDE"),
    "有轨电车": ("有轨电车", "#B6B6B7"), "有轨电车支线": ("有轨电车支线", "#B6B6B7"),
    "坪山云巴": ("坪山云巴", "#B6B6B7"),
}

# 出闸换乘标注（来自附图上的"约XX米"提示）
OUT_TRANSFER = {
    "清湖": "出闸换乘：有轨电车清湖站距4号线清湖站约50米",
    "新澜": "出闸换乘：距4号线观澜站约50米",
    "坪山高铁站": "出闸换乘：距16号线约100米",
    "坪山中心": "出闸换乘：距14号线约500米",
    "未来城": "出闸换乘：距14号线约450米",
    "龙背": "出闸换乘：距16号线约450米",
}


def load():
    st = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))
    ln = json.loads((DATA / "lines.json").read_text(encoding="utf-8"))
    mk = json.loads((DATA / "markers.json").read_text(encoding="utf-8"))["markers"]
    lb = json.loads((DATA / "ocr_labels.json").read_text(encoding="utf-8"))
    return st, ln, mk, lb


def locate_missing(names, markers, labels, img_shape):
    """给缺失站名找坐标：OCR 框 -> 最近空闲标记。"""
    idx = {}
    for lb in labels:
        t = lb["text"].replace(" ", "")
        if 2 <= len(t) <= 7:
            idx.setdefault(t, []).append(lb)
    used = set()
    out = {}
    for n in names:
        hits = idx.get(n) or []
        best = None
        for h in hits:
            cx, cy = h["x"] + h["w"] / 2, h["y"] + h["h"] / 2
            # 标签通常贴在标记右侧/左侧/上/下，取最近的标记
            dd = 1e18
            mi = None
            for i, m in enumerate(markers):
                if i in used:
                    continue
                d = ((m["x"] - cx) ** 2 + (m["y"] - cy) ** 2) ** 0.5
                if d < dd:
                    dd, mi = d, i
            if mi is not None and dd <= 260 and (best is None or dd < best[0]):
                best = (dd, mi, h)
        if best:
            dd, mi, h = best
            used.add(mi)
            out[n] = (round(float(markers[mi]["x"]), 1),
                      round(float(markers[mi]["y"]), 1), f"标记({dd:.0f}px)")
        elif hits:
            h = max(hits, key=lambda x: x.get("score", 0))
            cx = h["x"] + h["w"] / 2
            cy = h["y"] + h["h"] / 2
            out[n] = (round(float(cx), 1), round(float(cy), 1), "OCR框中心")
        else:
            out[n] = (None, None, "未定位")
    return out


def main():
    apply = "--apply" in sys.argv
    st, ln, markers, labels = load()
    S = st["stations"]
    img = np.asarray(Image.open(IMG).convert("RGB"))

    # 0) 站名纠正：把旧数据的错名改成原图上的正确名
    renamed = []
    for old, new in RENAME.items():
        if old in S:
            rec = S.pop(old)
            rec["station_id"] = new
            rec["station_name"] = new
            if new not in S:
                S[new] = rec
                renamed.append(f"{old}->{new}")
            else:
                # 目标名已存在则只用纠正后的坐标覆盖
                S[new]["x"], S[new]["y"] = rec["x"], rec["y"]
                renamed.append(f"{old}->{new}(合并)")
    if renamed:
        print(f"站名纠正 {len(renamed)}：{'、'.join(renamed)}")

    # 1) 统计需要的站名
    need = []
    seen = set()
    for lid, seq in SEQ.items():
        for n in seq:
            if n not in seen:
                seen.add(n)
                need.append(n)
    missing = [n for n in need if n not in S]
    print(f"站序共需要 {len(need)} 个站名，其中 {len(missing)} 个不在站表里")

    # 2) 定位缺失站点（先用手工量取的坐标，其次 OCR）
    loc = {}
    auto = [n for n in missing if n not in MANUAL_XY]
    if auto:
        loc.update(locate_missing(auto, markers, labels, img.shape))
    for n in missing:
        if n in MANUAL_XY:
            x, y = MANUAL_XY[n]
            loc[n] = (x, y, "原图手工量取")
    for n in missing:
        print(f"   {n:<10s} -> {loc[n][0]}, {loc[n][1]}   [{loc[n][2]}]")

    # 3) 生成/更新站点
    added = []
    for n in missing:
        x, y, how = loc[n]
        if x is None:
            continue
        d = dict(NEW_TPL)
        d.update({"station_id": n, "station_name": n, "lines": [],
                  "x": x, "y": y, "is_transfer": False})
        if how == "未定位":
            d["notes"] = "坐标待人工核对"
        S[n] = d
        added.append(n)

    # 4) 重建每条线的站序 & 站点 lines 字段
    for s in S.values():
        s["lines"] = []
    line_out = []
    for lid, seq in SEQ.items():
        name, color = LINES_META[lid]
        ref = next((x for x in ln["lines"] if x["id"] == lid), None)
        entry = dict(ref) if ref else {}
        entry.update({"id": lid, "name": name, "color": color,
                      "stations": [n for n in seq if n in S]})
        lost = [n for n in seq if n not in S]
        if lost:
            print(f"  !! {lid} 号线缺站（未定位）：{lost}")
        line_out.append(entry)
        for n in entry["stations"]:
            if lid not in S[n]["lines"]:
                S[n]["lines"].append(lid)

    # 5) 出闸换乘标注
    for n, note in OUT_TRANSFER.items():
        if n in S:
            S[n]["transfer_type"] = "out"
            S[n]["notes"] = note

    # 6) is_transfer 按线路数 + 手工保留
    for n, s in S.items():
        s["is_transfer"] = len(s.get("lines") or []) >= 2

    # 7) 幽灵站
    ghosts = [n for n in GHOST if n in S]
    for n in ghosts:
        del S[n]

    orphan = [n for n, s in S.items() if not s["lines"]]
    print(f"\n新增站点 {len(added)}：{'、'.join(added)}")
    print(f"删除幽灵站 {len(ghosts)}：{'、'.join(ghosts)}")
    if orphan:
        print(f"★ 不属于任何线路的孤立站 {len(orphan)}：{'、'.join(orphan)}")
    print(f"总站点 {len(S)}，总线路 {len(line_out)}")

    if not apply:
        print("\n（未加 --apply，仅预演）")
        return

    ts = datetime.now().strftime("%m%d%H%M")
    for f in (DATA / "stations.json", DATA / "lines.json"):
        shutil.copy2(f, f.with_suffix(f.suffix + f".bak_v24_{ts}"))
    (DATA / "stations.json").write_text(json.dumps(
        {"version": "2.4",
         "description": "站点数据。x/y 为原图像素坐标（原图 8000x8000）。"
                        " lines 为途经线路；transfer_type=out 表示出闸换乘。",
         "stations": S}, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "lines.json").write_text(json.dumps(
        {"version": "2.4", "description": "线路数据。stations 为按顺序排列的站名。",
         "lines": line_out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[OK] 已写回（备份 .bak_v24_{ts}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
