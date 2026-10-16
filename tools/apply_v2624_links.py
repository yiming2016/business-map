# -*- coding: utf-8 -*-
"""v2.6.24 数据补丁（幂等，可反复跑）：

① **福田口岸拆成两个站体**（用户原话「福田口岸4号线和10号线是独立开的」）。
   原图实测（`tools/_census_dashes.py` 扫 #8B8B8C 灰像素）：
   4号线站体 (3520,5949)、10号线站体 (3609,5949)，中间一条横向灰虚线。
   ⇒ 主坐标保留 4 号线那个，10 号线那个进 `alt_bodies`；**删掉 pill**
     （原图这里是两个独立小圆，不是一个药丸）。

② **补两条出站换乘虚线**（用户点名要的）：
     老街 ↔ 东门、大剧院 ↔ 红岭南
   ★★ 但要如实记一笔：**这两处在原图上其实没有虚线**。用颜色计数扫过
      「老街↔东门」和「大剧院↔红岭南」两块矩形，灰色像素只有零散几十个
      （全是黑字的抗锯齿边），不构成虚线。原图全部虚线就三条：
      湖贝 / 红岭南 / 福田口岸。这里按用户明确要求补，米数**留空不编**。

用法：
    python tools/apply_v2624_links.py            # 落盘
    python tools/apply_v2624_links.py --dry      # 只看会改什么
"""
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
P = SRC / "data" / "stations.json"
DRY = "--dry" in sys.argv

doc = json.loads(P.read_text(encoding="utf-8"))
st = doc["stations"]
changed = []

# ---------- ① 福田口岸 ----------
FT = st.get("福田口岸")
if FT is None:
    raise SystemExit("数据里没有『福田口岸』")
ALTS = [{"x": 3609.0, "y": 5949.0, "line": "10", "distance": ""}]
if FT.get("alt_bodies") != ALTS:
    FT["alt_bodies"] = ALTS
    changed.append("福田口岸：加 10 号线副站体 (3609,5949)")
if FT.get("pill") is not None:
    FT.pop("pill", None)
    changed.append("福田口岸：删 pill（原图是两个独立小圆，不是一个药丸）")
if "10" not in (FT.get("lines") or []):
    FT["lines"] = ["4", "10"]
    changed.append("福田口岸：lines 补回 ['4','10']")

# ---------- ② 两条出站换乘虚线 ----------
WANT = [
    ("老街", "东门"),
    ("大剧院", "红岭南"),
]
links = doc.setdefault("transfer_links", [])
have = {(d.get("a"), d.get("b")) for d in links}
have |= {(d.get("b"), d.get("a")) for d in links}
for a, b in WANT:
    if a not in st or b not in st:
        print("[SKIP] %s / %s 不存在" % (a, b))
        continue
    if (a, b) in have:
        continue
    links.append({"a": a, "b": b, "distance": ""})
    changed.append("transfer_links：加 %s ↔ %s（米数留空，用户没给也没在原图找到）" % (a, b))

# ---------- 校验 ----------
for nm in ("福田口岸", "老街", "东门", "大剧院", "红岭南"):
    assert nm in st, nm
alts = st["福田口岸"]["alt_bodies"]
assert alts and alts[0]["line"] == "10" and alts[0]["x"] != st["福田口岸"]["x"], "副站体必须错开"
print("transfer_links 现在 %d 条：" % len(links))
for d in links:
    print("   %-8s ↔ %-8s  %s" % (d.get("a"), d.get("b"), d.get("distance") or "(无米数)"))

if not changed:
    print("已经是目标状态，无需改动")
else:
    print("\n将改动 %d 处：" % len(changed))
    for c in changed:
        print("   ·", c)
    if DRY:
        print("\n(--dry，不落盘)")
    else:
        P.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n已写入 %s" % P)
