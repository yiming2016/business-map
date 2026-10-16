# -*- coding: utf-8 -*-
"""v2.6.21 数据补丁（幂等，自动备份）：

1) 新增顶层 `through_links`：**同一列车贯通运营**的两条线端点站。
   用户原话：「2号线到莲塘为止，但实际和8号线的『梧桐山南』是一辆列车」
             「梧桐山南连按照一条线路那样连起来即可」
   ⇒ 莲塘（2号线终点）↔ 梧桐山南（8号线起点）要画成**一条连续的实线**。
   渲染端（ui/map_view.rebuild_lines）会据此给两条线各补上对方的端点站。

2) 修正两处**米数互换**（用户在聊天里给的清单为准）：
   · 龙背 ↔ 东纵纪念馆：450 → **500** 米
   · 坪山中心（副站体）：500 → **450** 米
   清单原文：
       清湖➡️清湖 50m / 新澜➡️观澜 50m / 龙背➡️东纵纪念馆 500m
       未来城➡️坪山广场 450m / 坪山中心➡️坪山中心 450m / 坪山高铁站➡️坪山 100m
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "data" / "stations.json"

THROUGH = [{"a": "莲塘", "b": "梧桐山南", "note": "2号线/8号线贯通运营，同一列车"}]

FIX_DIST = {
    # ★ 键的类型要分清：transfer_links 用 "a|b" 字符串，alt_bodies 用 ("alt", 站名) 元组
    #   （第一版把前者也写成元组 ⇒ `key in FIX_DIST` 恒 False，龙背那条静默没改）
    "龙背|东纵纪念馆": "约500米",
    ("alt", "坪山中心"): "约450米",
}


def main() -> int:
    doc = json.loads(ST.read_text(encoding="utf-8"))
    bak = ST.with_name(ST.name + ".bak_through_" + time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(ST, bak)
    print("备份 →", bak.name)

    n = 0

    # ---- 1) through_links ----
    old = doc.get("through_links")
    if old == THROUGH:
        print("1) through_links 已是最新，跳过")
    else:
        doc["through_links"] = THROUGH
        print("1) through_links 写入：", "；".join("%s↔%s（%s）" % (d["a"], d["b"], d["note"])
                                                  for d in THROUGH))
        n += 1

    # ---- 2) 米数 ----
    for d in doc.get("transfer_links", []):
        key = "%s|%s" % (d["a"], d["b"])
        if key in FIX_DIST:
            new = FIX_DIST[key]
            if d.get("distance") != new:
                print("2) transfer_links %s：%s → %s" % (key, d.get("distance"), new))
                d["distance"] = new
                n += 1
    stations = doc["stations"]
    it = list(stations.values()) if isinstance(stations, dict) else stations
    for s in it:
        nm = s.get("station_name")
        if ("alt", nm) in FIX_DIST:
            new = FIX_DIST[("alt", nm)]
            for b in (s.get("alt_bodies") or []):
                if b.get("distance") != new:
                    print("2) alt_bodies %s：%s → %s" % (nm, b.get("distance"), new))
                    b["distance"] = new
                    n += 1

    # ---- 校验：through_links 的两端必须真实存在，且确实分属两条线 ----
    err = []
    by_name = {s.get("station_name"): s for s in it}
    for d in doc.get("through_links", []):
        for k in ("a", "b"):
            if d[k] not in by_name:
                err.append("through_links 的 %s=%s 不在库里" % (k, d[k]))
    for d in doc.get("transfer_links", []):
        for k in ("a", "b"):
            if d[k] not in by_name:
                err.append("transfer_links 的 %s=%s 不在库里" % (k, d[k]))
    a, b = by_name.get("莲塘"), by_name.get("梧桐山南")
    if a and b:
        print("   莲塘 lines=%s ｜ 梧桐山南 lines=%s" % (a.get("lines"), b.get("lines")))
        if set(a.get("lines") or []) & set(b.get("lines") or []):
            err.append("莲塘与梧桐山南被登记成同一条线的站了，贯通连接会画重")
    if err:
        print("\n[FAIL] 校验不通过：")
        for e in err:
            print("   -", e)
        return 1

    ST.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[OK] 写入 %s（改动 %d 处，幂等）" % (ST.name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
