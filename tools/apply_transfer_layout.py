# -*- coding: utf-8 -*-
"""把 tools/measure_transfer_layout.py 量到的「胶囊几何 + 线路走廊偏移」写进 data/stations.json。

写入字段（只对 is_transfer=True 的站）：
  "pill":  {"ang": 0..180, "len": 原图内部长(px), "wid": 原图内部宽(px)}
  "lanes": {"7": [dx, dy], ...}   该线走廊中心相对站中心的偏移（原图像素）

幂等：重复执行结果一致。执行前自动备份。
"""
import json
import math
import shutil
import time
from pathlib import Path

SRC = Path("C:/software/subway/源码")
ST_PATH = SRC / "data/stations.json"
TL_PATH = SRC / "data/transfer_layout.json"

st_raw = json.loads(ST_PATH.read_text(encoding="utf-8"))
ST = st_raw["stations"]
TL = json.loads(TL_PATH.read_text(encoding="utf-8"))

bak = ST_PATH.with_name("stations.json.bak_pill_%s" % time.strftime("%Y%m%d_%H%M%S"))
shutil.copy2(ST_PATH, bak)

n_pill = n_lane = n_skip = n_drop = 0
for nm, rec in TL.items():
    s = ST.get(nm)
    if s is None or not s.get("is_transfer"):
        n_skip += 1
        continue
    p = rec.get("pill")
    if not p:
        continue
    s["pill"] = {
        "ang": round(float(p["ang"]), 1),
        "len": round(float(p["rl"]) * 2 + 1),
        "wid": round(float(p["rs"]) * 2),
    }
    n_pill += 1
    # ★★ 走廊偏移的合理性过滤（v2.6.20）：
    #   偏移不可能超出药丸本身 —— 药丸就是用来"横跨几条走廊"的。
    #   实测 `福田口岸` 的 10 号线量出 87.3px（而它的药丸只有 25×23），
    #   那是把附近的另一段同色线错认成它的走廊（真实是"同名两站体"，
    #   10 号线在别处另有一个圆点）。这种超界的一律丢掉，退回"线过站中心"。
    _limit = max(float(p["rl"]), float(p["rs"])) + float(p["rs"]) + 20.0
    lanes = {}
    for k, v in (rec.get("lanes") or {}).items():
        if math.hypot(float(v[0]), float(v[1])) > _limit:
            n_drop += 1
            continue
        lanes[str(k)] = [round(float(v[0]), 1), round(float(v[1]), 1),
                         round(float(v[2]), 1), round(float(v[3]), 2)]
    if lanes:
        s["lanes"] = lanes
        n_lane += len(lanes)

ST_PATH.write_text(json.dumps(st_raw, ensure_ascii=False, indent=1), encoding="utf-8")
print("备份 ->", bak.name)
print("写入胶囊 %d 个站 / 走廊 %d 条；跳过（非换乘站）%d 个；丢弃超界走廊 %d 条"
      % (n_pill, n_lane, n_skip, n_drop))
