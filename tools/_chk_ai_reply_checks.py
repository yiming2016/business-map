# -*- coding: utf-8 -*-
"""
自检：确认 check_ai_reply.py 真的能抓出错误。

一个"从不报错"的校验器等于没有。所以这里**故意把回传 JSON 搞坏**成十几种
典型错误，再跑校验器，看它有没有在正确的位置报出正确的错。
（这些错误都是从真实踩坑里来的：station_id 写错会凭空新建站点、
AI 漏填 <FILL>、写了价格数字、写了出口编号、套了 Markdown 围栏…）

用法：python tools/_chk_ai_reply_checks.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
PY = sys.executable
CHECKER = SRC / "tools" / "check_ai_reply.py"
BATCH01 = SRC / "站点文案" / "批次01.txt"
FAKE_MAKER = Path(r"C:\Windows\Temp\wb_reply_test\_make_fake_reply.py")

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print("%s %s%s" % ("✅" if ok else "❌", name, ("  " + detail) if detail else ""))


def ensure_fake_reply() -> Path:
    """先确保有一份"合格"的模拟回传可用（没有就现场造一份）。"""
    p = Path(r"C:\Windows\Temp\wb_reply_test\批次01.json")
    if not p.exists():
        if FAKE_MAKER.exists():
            subprocess.run([PY, str(FAKE_MAKER)], check=True,
                           stdout=subprocess.DEVNULL)
        else:
            raise SystemExit("!! 缺少模拟回传文件，也找不到生成脚本：%s" % FAKE_MAKER)
    return p


def run_checker(reply: Path, rehearse: bool = False):
    cmd = [PY, str(CHECKER), "--reply", str(reply), "--batch", str(BATCH01)]
    if rehearse:
        cmd.append("--rehearse")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mutate(base: dict, fn) -> dict:
    d = json.loads(json.dumps(base))
    fn(d)
    return d


def write_case(tmp: Path, name: str, obj, as_text: str | None = None) -> Path:
    p = tmp / name
    if as_text is not None:
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(as_text)
    else:
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    return p


def main() -> int:
    fake = ensure_fake_reply()
    base = json.loads(fake.read_text(encoding="utf-8-sig"))
    tmp = Path(tempfile.mkdtemp(prefix="wbreply_selfcheck_"))

    # ---------- 0. 合格样本必须通过（否则后面全是假阳性）----------
    rc, out = run_checker(fake)
    record("合格样本通过（对照组）", rc == 0 and "问题 0 条" in out,
           "rc=%d" % rc)

    # ---------- 1. 少一条 ----------
    p = write_case(tmp, "少一条.json", mutate(base, lambda d: d["stations"].pop()))
    rc, out = run_checker(p)
    record("少一条 → 报条数不对且点出缺谁",
           rc != 0 and "条数" in out and "少了这些站点" in out, "")

    # ---------- 2. ★ station_id 被改名（历史孤儿站的成因）----------
    def rename(d):
        d["stations"][0]["station_id"] = d["stations"][0]["station_id"] + "X"
    p = write_case(tmp, "改名.json", mutate(base, rename))
    rc, out = run_checker(p)
    record("station_id 被改名 → 报多了/不在数据里",
           rc != 0 and "多了这些站点" in out and "不在真实数据里" in out, "")
    rc, out = run_checker(p, rehearse=True)
    record("改名 + 试导入 → 站点数变多被拦住",
           rc != 0 and ("站点数变了" in out or "被当成新站" in out), "")

    # ---------- 3. 漏填 <FILL> ----------
    def keep_fill(d):
        d["stations"][2]["notes"] = "<FILL>"
    p = write_case(tmp, "漏填.json", mutate(base, keep_fill))
    rc, out = run_checker(p)
    record("漏填 <FILL> → 报没替换", rc != 0 and "还是 <FILL>" in out, "")

    # ---------- 4. 营销词 ----------
    def mkt(d):
        d["stations"][1]["description"] += "这里是创业者的首选。"
    p = write_case(tmp, "营销词.json", mutate(base, mkt))
    rc, out = run_checker(p)
    record("营销词「首选」→ 报出来", rc != 0 and "营销词" in out, "")

    # ---------- 5. 写了数字（价格）----------
    def price(d):
        d["stations"][3]["description"] += "周边店铺人均消费约 50 元。"
    p = write_case(tmp, "数字.json", mutate(base, price))
    rc, out = run_checker(p)
    record("价格数字 → 报出来", rc != 0 and "里有数字" in out, "")

    # 线路号里的数字不该被误报（正例）
    def linenum(d):
        d["stations"][4]["description"] += "本站位于 1 号线与 11 号线交汇片区。"
    p = write_case(tmp, "线路号.json", mutate(base, linenum))
    rc, out = run_checker(p)
    record("线路编号「1号线」不误报（正例）", rc == 0, "rc=%d" % rc)

    # ★ 2026-09-24 真回传里踩到的三种误报（原来只认 "N号线"，下面全被误伤）：
    #   删掉它们反而会丢掉必要信息，所以各补一条正例钉住。
    # 注意：base 样本只有 8 条，每个 case 都是 mutate() 出来的**独立副本**，
    #       所以三条可以复用同一个下标。
    for i, (tag, tail) in enumerate([
        ("顿号分隔多线路号「1、11、12号线」", "本站为 1、11、12号线交汇枢纽。"),
        ("航站楼编号「T3航站楼」", "紧邻 T3航站楼，出站即达。"),
        ("营业时长「24小时」", "毗邻 24小时通关口岸，深夜客流仍活跃。"),
    ]):
        def mk(tail=tail):
            def f(d):
                d["stations"][7]["landmarks"] += tail
            return f
        p = write_case(tmp, "误报_%d.json" % i, mutate(base, mk()))
        rc, out = run_checker(p)
        record("%s 不误报（正例）" % tag, rc == 0,
               "rc=%d %s" % (rc, out.strip().splitlines()[-1][:60] if out.strip() else ""))

    # ---------- 6. 出口编号 ----------
    def exitno(d):
        d["stations"][5]["notes"] = "从 A 口出站更近。"
    p = write_case(tmp, "出口编号.json", mutate(base, exitno))
    rc, out = run_checker(p)
    record("出口编号 A 口 → 报出来", rc != 0 and "出口编号" in out, "")

    # ---------- 7. 混进事实字段 exits ----------
    def add_exits(d):
        d["stations"][6]["exits"] = "A口 在宝安大道东侧"
    p = write_case(tmp, "混exits.json", mutate(base, add_exits))
    rc, out = run_checker(p)
    record("混进 exits 字段 → 报出来",
           rc != 0 and "混进了事实字段" in out and "键不对" in out, "")

    # ---------- 8. emoji + Markdown + 换行 ----------
    def emo(d):
        d["stations"][7]["description"] += "很不错😀"
    p = write_case(tmp, "emoji.json", mutate(base, emo))
    rc, out = run_checker(p)
    record("emoji → 报出来", rc != 0 and "emoji" in out, "")

    def md(d):
        d["stations"][7]["notes"] = "**重点**注意人流量"
    p = write_case(tmp, "markdown.json", mutate(base, md))
    rc, out = run_checker(p)
    record("Markdown 加粗 → 报出来", rc != 0 and "Markdown" in out, "")

    def nl(d):
        d["stations"][7]["notes"] = "第一行\n第二行"
    p = write_case(tmp, "换行.json", mutate(base, nl))
    rc, out = run_checker(p)
    record("正文里塞换行 → 报出来", rc != 0 and "里有换行" in out, "")

    # ---------- 9. 8 条句式雷同 ----------
    def same(d):
        for r in d["stations"]:
            r["description"] = "位于宝安片区，周边以居住和商业为主。" + r["description"][8:]
    p = write_case(tmp, "雷同.json", mutate(base, same))
    rc, out = run_checker(p)
    record("8 条开头雷同 → 报套模板", rc != 0 and "开头雷同" in out, "")

    # ---------- 10. 必填栏空着 ----------
    def empty_desc(d):
        d["stations"][0]["description"] = ""
    p = write_case(tmp, "空简介.json", mutate(base, empty_desc))
    rc, out = run_checker(p)
    record("简介留空 → 报必填", rc != 0 and "是空的" in out, "")

    # ---------- 11. 套 Markdown 围栏 + 前后加解释（要能扛住）----------
    text = ("好的，这是你要的 JSON：\n\n```json\n"
            + json.dumps(base, ensure_ascii=False, indent=2)
            + "\n```\n\n希望对你有帮助！")
    p = write_case(tmp, "带围栏.txt", None, as_text=text)
    rc, out = run_checker(p)
    record("套了 ```json 围栏 + 前后废话 → 仍能解析通过",
           rc == 0 and "解析成功" in out, "rc=%d" % rc)

    # ---------- 12. 带 BOM 的 UTF-8（记事本另存）----------
    p = write_case(tmp, "带BOM.json", None,
                   as_text="\ufeff" + json.dumps(base, ensure_ascii=False, indent=2))
    rc, out = run_checker(p)
    record("UTF-8 带 BOM → 仍能解析通过", rc == 0 and "解析成功" in out, "rc=%d" % rc)

    # ---------- 13. UTF-16（记事本"Unicode"选项）----------
    p = tmp / "UTF16.json"
    p.write_bytes(json.dumps(base, ensure_ascii=False).encode("utf-16"))
    rc, out = run_checker(p)
    record("UTF-16 编码 → 仍能解析通过", rc == 0 and "解析成功" in out, "rc=%d" % rc)

    # ---------- 14. 截断的文件 ----------
    p = write_case(tmp, "截断.json", None,
                   as_text=json.dumps(base, ensure_ascii=False)[:200])
    rc, out = run_checker(p)
    record("文件被截断 → 明确报解析失败", rc != 0 and "解析失败" in out, "")

    # ---------- 15. 合格样本 + 试导入（正例，必须全绿）----------
    rc, out = run_checker(fake, rehearse=True)
    ok = (rc == 0 and "导入后站点数 : 379" in out and "新增 0" in out
          and "分毫未动" in out)
    record("合格样本 + 试导入 → 379/379、新增 0、其余未动", ok, "rc=%d" % rc)

    # ---------- 汇总 ----------
    bad = [n for n, ok, _ in RESULTS if not ok]
    print("=" * 70)
    print("共 %d 项，通过 %d 项，失败 %d 项" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    if bad:
        print("失败项：")
        for n in bad:
            print("   ❌ %s" % n)
    print("结论：%s" % ("校验器的每一条判定都能被触发 ✅" if not bad else "有判定失灵 ❌"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
