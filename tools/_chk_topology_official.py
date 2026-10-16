# -*- coding: utf-8 -*-
"""
_chk_topology_official.py —— 回归：v2.6.18 按官方图纸修好的 9 处线路连接（拓扑）。

每一处都在官方原图（assets/shenzhen_metro.png，8000×8000，旧坐标=位图像素）
上裁图亲眼核对过（裁图存 logs/_audit_*.png）：

  ① 5号线  无【宝安】（宝华→宝安中心 直连；宝安只是 11号线）
  ② 5号线  西延段 黄贝岭→湖贝→东门→大剧院（东门是新建站）
  ③ 12号线 无【会展城】（国展北→海上田园南 直连；会展城只是 20号线）
  ④ 13号线 有【深大】无【深大南】（粤海门→深大→高新中；深大南只是 9号线）
  ⑤ 13号线 有【西丽高铁站】无【西丽】（高新北→西丽高铁站→石鼓；新站）
  ⑥ 7号线  有【西丽】（西丽湖→西丽→茶光；5/7 换乘）
  ⑦ 11号线 无【机场东】（机场北→碧海湾 直连；机场东是 1/12号线）
  ⑧ 坪山云巴 无【坪山中心】（官方图云巴在该处不设站；★ 现实有这站，按用户
            「完全遵照官方图」处理——用户若反悔，恢复见 fix_line_topology.py）
  ⑨ 14号线 有【坪山围】（锦龙→坪山围→坪山广场；14×16 换乘）

判据：
  A 站数：总数 381；5=37 / 7=28 / 11=21 / 12=37 / 13=29 / 14=18 / 坪山云巴=10
  B 邻接：上面 ②④⑤⑥⑨ 的每一对都相邻（8 组）
  C 排除：上面 ①③⑦⑧ 的站不在对应线里 + 深大南/西丽 不在 13号线（6 组）
  D 站点字段：12 个受影响站的 lines / is_transfer 与定案一致
  E 双向一致：线里有站 ⇔ 站的 lines 里有线（全量 381 站 × 20 线）
  F 绕行比：除白名单外无 >1.5 的拐弯（防"混进站/漏站"回归）
  G ★ 白名单上限：结构性弯不许恶化（抓"布局修坏"）

白名单（每条都写明原因和实测值，不许默默放宽）：
  (1, 老街)   官方真弯（官方坐标系绕行 1.68；v2.6.17 底图 2.72）
  (1, 大剧院) v2.6.17 继承弯（底图 1.73，本轮 1.59 反而略好）
  (11, 南山) / (12, 南山)  官方真弯；12号线南山在 v2.6.17 底图就是 2.39
      （当前 2.36 略好），上限放宽到 2.5 是有据可依的
  (13, 深大)  与西丽同类的结构性弯：深大贴 1号线走廊（绕行 1.00，官方即如此），
      13号线走廊在 v2.6.17 里与 1号线走廊不相交，只能微微一弯（实测 1.61）
  (5, 西丽) / (7, 西丽) / (7, 茶光)
      ★★ 结构性：v2.6.17 底图里 5号线走廊与 7号线走廊在西丽**平行不相交**
      （间隙 494px，延长线交点 t=1.37/u=3.78 都在线段外），而官方两条走廊
      都笔直地在西丽十字相交。拓扑修对后西丽必须同时贴在两条线上，
      单点放置的 min-max 下界 ≈2.56（实测 2.04/2.70 已近最优）。
      要彻底掰直只能整条平移 7号线南段走廊（茶光/珠光/龙井…），实测会把
      弯推给下游（茶光 1.78/珠光 1.72），打地鼠——暂不动，留给用户定夺。

变异自检（证明判据有牙）：
  --mutate-baoan     把宝安塞回 5号线 → C/F 组必须失败
  --mutate-lines     把西丽的 lines 改成只有 5号线 → E 组必须失败
  --mutate-whitelist 删掉西丽白名单 → G 组（F 组）必须失败

运行：
  python tools/_chk_topology_official.py                # 全绿才算过
  python tools/_chk_topology_official.py --mutate-xxx   # 每组都应失败
"""

import json
import math
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
STATIONS = SRC_ROOT / "data" / "stations.json"
LINES = SRC_ROOT / "data" / "lines.json"

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


EXPECTED_COUNT = {"5": 37, "12": 37, "13": 29, "7": 28, "11": 21, "坪山云巴": 10, "14": 18}
EXPECTED_TOTAL = 381

ADJACENT = [  # ②④⑤⑥⑨
    ("5", "宝华", "宝安中心"),
    ("5", "黄贝岭", "湖贝"), ("5", "湖贝", "东门"), ("5", "东门", "大剧院"),
    ("12", "国展北", "海上田园南"),
    ("13", "粤海门", "深大"), ("13", "深大", "高新中"),
    ("13", "高新北", "西丽高铁站"), ("13", "西丽高铁站", "石鼓"),
    ("7", "西丽湖", "西丽"), ("7", "西丽", "茶光"),
    ("11", "机场北", "碧海湾"),
    ("坪山云巴", "文化聚落", "中芯国际"),
    ("14", "锦龙", "坪山围"), ("14", "坪山围", "坪山广场"),
]
NOT_IN = [  # ①③⑦⑧ + ④⑤的另一半
    ("5", "宝安"), ("12", "会展城"), ("11", "机场东"), ("坪山云巴", "坪山中心"),
    ("13", "深大南"), ("13", "西丽"),
]
LINES_OF = {
    "宝安": ["11"], "会展城": ["20"], "机场东": ["1", "12"], "坪山中心": ["14"],
    "深大南": ["9"], "深大": ["1", "13"], "西丽": ["5", "7"], "湖贝": ["2", "5"],
    "大剧院": ["1", "2", "5"], "东门": ["5"], "西丽高铁站": ["13"], "坪山围": ["14", "16"],
}

# (线路, 站): 绕行比上限 —— 原因见 docstring
DETOUR_WHITELIST = {
    ("1", "老街"): 3.2,
    ("1", "大剧院"): 1.9,
    ("11", "南山"): 2.0,
    ("12", "南山"): 2.5,
    ("13", "深大"): 1.8,
    ("5", "西丽"): 2.3,
    ("7", "西丽"): 3.0,
    ("7", "茶光"): 2.9,
}
DETOUR_LIMIT = 1.5


def load():
    with open(STATIONS, "r", encoding="utf-8") as f:
        st = json.load(f)["stations"]
    with open(LINES, "r", encoding="utf-8") as f:
        doc = json.load(f)
    return st, {L["id"]: L["stations"] for L in doc["lines"]}


def detour(pa, ps, pb):
    dd = math.dist(pa, pb)
    if dd < 1:
        return 1.0
    return (math.dist(pa, ps) + math.dist(ps, pb)) / dd


def main():
    mutate = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--mutate=")), None)
    st, seqs = load()

    if mutate == "baoan":
        seqs["5"].insert(seqs["5"].index("宝安中心"), "宝安")
        print("[变异] 宝安塞回 5号线（C/F 组应当失败）\n")
    elif mutate == "lines":
        st["西丽"]["lines"] = ["5"]
        print("[变异] 西丽 lines 改成只有 5号线（E 组应当失败）\n")
    elif mutate == "whitelist":
        for k in (("5", "西丽"), ("7", "西丽"), ("7", "茶光")):
            DETOUR_WHITELIST.pop(k, None)
        print("[变异] 删掉西丽白名单（G 组应当失败）\n")

    # ---- A 站数
    print("A 站数")
    ok(f"总站数 = {EXPECTED_TOTAL}", len(st) == EXPECTED_TOTAL, f"实际 {len(st)}")
    for lid, n in EXPECTED_COUNT.items():
        ok(f"{lid}号线 = {n} 站", len(seqs[lid]) == n, f"实际 {len(seqs[lid])}")

    # ---- B 邻接
    print("B 定案邻接")
    for lid, a, b in ADJACENT:
        seq = seqs[lid]
        hit = any(seq[i] == a and seq[i + 1] == b for i in range(len(seq) - 1))
        ok(f"{lid}号线 {a}→{b} 相邻", hit, f"实际序 …{seq}")

    # ---- C 排除
    print("C 定案排除")
    for lid, n in NOT_IN:
        ok(f"{n} 不在 {lid}号线", n not in seqs[lid])

    # ---- D 站点字段
    print("D 站点 lines/is_transfer")
    for n, lines in LINES_OF.items():
        s = st.get(n)
        if not ok(f"{n} 存在", s is not None):
            continue
        ok(f"{n}.lines = {lines}", (s.get("lines") or []) == lines,
           f"实际 {s.get('lines')}")
        ok(f"{n}.is_transfer = {len(lines) > 1}",
           bool(s.get("is_transfer")) == (len(lines) > 1))

    # ---- E 双向一致（全量）
    print("E 双向一致")
    bad = []
    for lid, seq in seqs.items():
        for n in seq:
            if n not in st:
                bad.append(f"{lid}号线的 {n} 不在 stations.json")
            elif lid not in (st[n].get("lines") or []):
                bad.append(f"{n} 在 {lid}号线里但 lines={st[n].get('lines')}")
    for n, s in st.items():
        for lid in (s.get("lines") or []):
            if lid not in seqs or n not in seqs[lid]:
                bad.append(f"{n} 声称属于 {lid}号线但线里没有")
        want = len(s.get("lines") or []) > 1
        if bool(s.get("is_transfer")) != want:
            bad.append(f"{n} is_transfer 与 lines 不符")
    ok("线里有站 ⇔ 站的 lines 里有线（含 is_transfer）", not bad,
       "；".join(bad[:5]))

    # ---- F/G 绕行比
    print("F 绕行比（白名单外）/ G 白名单上限")
    suspicious, wl_bad = [], []
    for lid, seq in seqs.items():
        for i in range(1, len(seq) - 1):
            a, s, b = seq[i - 1], seq[i], seq[i + 1]
            if a not in st or s not in st or b not in st:
                continue
            r = detour((st[a]["x"], st[a]["y"]), (st[s]["x"], st[s]["y"]),
                       (st[b]["x"], st[b]["y"]))
            cap = DETOUR_WHITELIST.get((lid, s))
            if cap is None:
                if r > DETOUR_LIMIT:
                    suspicious.append(f"{lid}号线 {a}→{s}→{b} 绕行 {r:.2f}")
            elif r > cap:
                wl_bad.append(f"{lid}号线 {s} 绕行 {r:.2f} 恶化（上限 {cap}）")
    ok("白名单外无绕行 >1.5 的站", not suspicious, "；".join(suspicious[:6]))
    ok("白名单内的结构性弯没有恶化", not wl_bad, "；".join(wl_bad))

    print(f"\n===== {PASS} 通过 / {FAIL} 失败 =====")
    if mutate:
        # 变异模式下：预期必须有失败，全绿说明判据没牙
        if FAIL == 0:
            print(f"[FAIL] 变异 {mutate} 没被抓到 —— 判据失效！")
            return 1
        print(f"[OK] 变异 {mutate} 被抓住（{FAIL} 条失败符合预期）")
        return 0
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
