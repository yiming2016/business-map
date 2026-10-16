# -*- coding: utf-8 -*-
"""
fetch_szmc_official.py —— 从深圳地铁**官网**拉取「站点查询」的官方数据。

数据源（一手，2026-09-24 摸到）：
  1. 线路/站点清单
     GET  https://www.szmc.net/styles/index/zdWeb/js/xlurlList.js
     里面有 `zdurl`：每条线路的站点数组 {name, nameen, code}
  2. 站点详情（★ 本脚本的核心）
     POST https://www.szmc.net/zdxx
     表单参数 **`StieCode`** + 4 位编号
     ★★ 官网把 Station 拼成了 `Stie`（漏了 a），**必须照抄**，改成 StatioCode 就取不到。

为什么一个站只查一次：
    换乘站**查它任意一条线的那条记录，返回里就含它在所有线路的班次表 + 全部出入口**。
    实测车公庙只查 1 号线的 0111，就拿到了 1/7/9/11 四条线的班次和 12 个出口。
    所以按**站名去重**即可，432 个「线路-站点」条目 → 351 个站。

落盘（默认 `源码/_data_szmc/`）：
    raw/<编号>.json        每个站的原始返回（留作凭证，便于以后追溯/重新转格式）
    stations_index.json    站名 → 编号、是否命中
    xlurlList.js           官网原始清单（留作凭证）

★ 只拉**我们自己数据里存在的站**（默认），别把官网全站都拉下来浪费请求。

用法：
    python tools/fetch_szmc_official.py                 # 拉缺失的（推荐）
    python tools/fetch_szmc_official.py --all           # 全部重拉（忽略已有缓存）
    python tools/fetch_szmc_official.py --only 车公庙 罗湖  # 只拉这几个站（调试用）
    python tools/fetch_szmc_official.py --delay 0.4     # 放慢（怕风控时用）
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "_data_szmc"
STATIONS_JSON = ROOT.parent / "软件" / "data" / "stations.json"

XL_URL = "https://www.szmc.net/styles/index/zdWeb/js/xlurlList.js"
ZD_URL = "https://www.szmc.net/zdxx"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ---------------------------------------------------------------- 网络
def http_get(url: str, timeout: int = 30, retry: int = 3) -> str:
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:                       # 网络抖动：重试，别一次放弃
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError("GET 失败 %s：%s" % (url, last))


def http_post(url: str, data: dict, timeout: int = 30, retry: int = 3) -> str:
    last = None
    body = urllib.parse.urlencode(data).encode("ascii")
    for i in range(retry):
        try:
            req = urllib.request.Request(
                url, data=body, headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError("POST 失败 %s：%s" % (url, last))


# ---------------------------------------------------------------- 解析清单
def parse_station_index(js_text: str) -> dict:
    """返回 {站名: {"codes": [编号...], "nameen": 英文名, "line": 线路号}}

    ★ 换乘客在同一个站名在官网 `zdurl` 里会出现多次（每条线路一次）。
      ★ 早期版本只保留第一条编号，结果踩坑：**有的编号官网返回的是空记录**。
        实测：银湖 `0605` 返回全空、`0923` 才有数据；国展 `1230` 空、`2003` 才有；
        国展北 `1231` 空、`2004` 才有。
      所以这里**保留该站名下所有编号**，抓的时候逐个试，取第一个真有数据的。
    """
    out: dict = {}
    pat = re.compile(
        r'name\s*:\s*"([^"]+)"\s*,\s*nameen\s*:\s*"([^"]*)"\s*,\s*code\s*:\s*"([^"]+)"')
    for m in pat.finditer(js_text):
        name, nameen, code = m.group(1), m.group(2), m.group(3)
        rec = out.setdefault(
            name, {"codes": [], "nameen": nameen,
                   "line": "6支" if code[:2] == "66" else code[:2]})
        if code not in rec["codes"]:
            rec["codes"].append(code)
    return out


def has_real_data(obj: dict) -> bool:
    """官网"查无此站"时返回的是一条**全空**记录（siteName == ""），必须认出来。"""
    if not str(obj.get("siteName") or "").strip():
        return False
    return bool(obj.get("outAndText") or obj.get("workDay")
                or obj.get("dayoff") or obj.get("holidays"))


def load_our_station_names() -> dict:
    doc = json.loads(STATIONS_JSON.read_text(encoding="utf-8"))
    return {sid: str(s.get("station_name", sid)).strip()
            for sid, s in doc["stations"].items()}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--all", action="store_true", help="全部重拉，忽略已有缓存")
    ap.add_argument("--only", nargs="*", default=[], help="只拉这几个站名（调试）")
    ap.add_argument("--delay", type=float, default=0.25, help="每次请求间隔秒")
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args()

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. 拉官网清单（并留作凭证）----
    print("拉取线路/站点清单 …")
    js = http_get(XL_URL)
    (out / "xlurlList.js").write_text(js, encoding="utf-8")
    index = parse_station_index(js)
    print("  官网清单：%d 个站名（已按站名去重）" % len(index))

    # ---- 2. 与我们自己的 379 站对齐 ----
    ours = load_our_station_names()
    by_name = {v: k for k, v in ours.items()}          # 站名 → station_id
    matched = {}
    missing = []
    for name, sid in sorted(by_name.items()):
        if name in index:
            matched[name] = index[name]
        else:
            missing.append(name)
    print("  我们 %d 站 → 官网能查到 %d 站，查不到 %d 站"
          % (len(ours), len(matched), len(missing)))

    if args.only:
        keep = set(args.only)
        before = len(matched)
        matched = {k: v for k, v in matched.items() if k in keep}
        print("  --only 命中 %d/%d（注意：名字必须和官网完全一致）"
              % (len(matched), before))
        if not matched:
            print("  一个都没命中，官网上的实际名字可能不同。退出。")
            return 1

    # ---- 3. 逐个编号拉取详情 ----
    # ★★ 一个站名在官网有多个编号（换乘站每条线路一个），而**不同编号返回的
    #    完整度不一样**：实测 上梅林 0407 → 0 个出口、简介"暂无数据"；
    #    0921 → 4 个出口 + 真简介。所以**每个编号都抓**，取最全的那份
    #    （谁最全由下游 import 工具按 score 挑，原始返回全部留档可追溯）。
    pairs = []                            # [(站名, 编号)]
    for name, info in matched.items():
        for code in info["codes"]:
            f = raw_dir / ("%s.json" % code)
            if args.all or not f.exists():
                pairs.append((name, code))
    pairs.sort(key=lambda kv: kv[1])

    print("  待拉取 %d 个编号（对应 %d 站；已有缓存的编号不会重拉，--all 强制）"
          % (len(pairs), len(matched)))

    ok_n = fail_n = 0
    failures = []
    for i, (name, code) in enumerate(pairs, 1):
        try:
            txt = http_post(ZD_URL, {"StieCode": code}, timeout=args.timeout)
            obj = json.loads(txt)                        # ★ 真解析一遍
        except Exception as e:
            fail_n += 1
            failures.append({"站名": name, "编号": code, "错误": str(e)})
            print("  [%3d/%3d] %-6s %-10s 失败：%s" % (i, len(pairs), code, name, e))
            time.sleep(args.delay)
            continue
        (raw_dir / ("%s.json" % code)).write_text(
            json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        tag = "" if has_real_data(obj) else "  （官网这条是空的/暂无数据）"
        print("  [%3d/%3d] %-6s %-10s 出入口%d 班次%d%s"
              % (i, len(pairs), code, name,
                 len(obj.get("outAndText") or []),
                 len(obj.get("workDay") or []), tag))
        ok_n += 1
        time.sleep(args.delay)

    # ---- 4. 落索引 & 缺失清单 ----
    idx = {
        "_说明": "站名 → 官网该站下所有编号（`codes`）。换乘站每条线路都有一个编号，"
                 "★ 不同编号返回的**完整度不一样**，下游 import 工具会按 score 挑最全那份；"
                 "编号本身可重复，原始返回全部按编号留档在 raw/ 下",
        "_抓取时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "_数据源": {"清单": XL_URL, "详情": "%s (POST StieCode=<编号>)" % ZD_URL},
        "已命中": {n: v for n, v in matched.items()},
        "查不到": sorted(missing),
    }
    (out / "stations_index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    if failures:
        (out / "failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        # ★ 一次跑通后必须把旧的 failures.json 删掉 —— 留着会让人以为还有问题
        stale = out / "failures.json"
        if stale.exists():
            stale.unlink()
            print("（已清除上一轮遗留的 failures.json）")

    print("\n成功 %d，失败 %d，跳过（查不到）%d" % (ok_n, fail_n, len(missing)))
    print("原始返回 → %s" % raw_dir)
    print("索引     → %s" % (out / "stations_index.json"))
    if failures:
        print("★ 失败的写在 %s，重跑本脚本会补上（有缓存的不会重拉）"
              % (out / "failures.json"))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
