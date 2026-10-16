# -*- coding: utf-8 -*-
"""回归：**手动调过的站名位置，关掉软件再打开必须一模一样**。

用户原话：「为什么我每次修改文字位置后再打开会丢失正确位置？」

★ 为什么必须是**两个独立进程**：
   同一个进程里 new 两个 MainWindow 不算"关掉再打开" —— 数据管理器是单例，
   第二个窗口可能直接读到内存里那份脏数据，等于从没关过，bug 就验不出来。
   所以这里用 subprocess 跑 `tools/_repro_label_lost.py` 两次（drag / reopen），
   中间真的落盘一次。

★ 病因（v2.6.60 修）：
   最终位置 = **方位摆位 + 手动偏移**。偏移（label_dx/dy）早就落盘了，
   但**方位**（_label_side / _side_lock）只活在内存里 —— 重开时排版器见到
   "这个站有偏移"就直接放行、不再给它挑方位 ⇒ 方位退回初始值 ⇒ 基点换了一个
   ⇒ 偏移叠上去差出几十像素（实测：上屋 拖动时 right1、重开变 right，差 60px）。
   修法 = 拖动时把方位一起写进 stations.json（`label_side`），加载时读回来。

判据：
  A 拖动后 vs 重开后，每个站名框的中心位移 ≤ 0.5px
  B 变异自检：METROEDITOR_NO_LABEL_SIDE=1（退回"只存偏移"）⇒ A 必须**失败**

用法：
    python tools/_chk_label_persist.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = sys.executable
REPRO = ROOT / "tools" / "_repro_label_lost.py"
# ★★ 样本站必须挑 **label_side ≠ official_label_side** 的（实测 383 站里有 124 个）：
#    只有这种站，"重开时读不到方位"才会真的退回另一个方位 ⇒ 位置才会错开。
#    原先那批（世界之窗/车公庙/黄木岗/机场东…）label_side 跟官方方位**本来就一样**
#    ⇒ 抹掉也没差 ⇒ 变异假通过（B1 曾长期红着，就是这个原因）。
DRAG_STATIONS = "上屋,白石洲,竹子林,华强路,科学馆,黄贝岭"
TOL = 0.5


def run_pair(tmp: Path, tag: str, mutate_between=None, env_extra=None):
    """跑 drag + reopen 两步，返回 (drag结果, reopen结果)。

    ★ `mutate_between(tmp)` 在 **drag 落盘之后、reopen 之前**被调用 —— 这才是
      "没存住"的真场景（变异要砍的是**存下来的那份**，不是输入的那份）。
    """
    out = {}
    for step in ("drag", "reopen"):
        if step == "reopen" and mutate_between is not None:
            mutate_between(tmp)
        f = tmp / ("%s_%s.json" % (tag, step))
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        r = subprocess.run([PY, str(REPRO), "--step", step, "--data", str(tmp),
                            "--out", str(f), "--drag", DRAG_STATIONS],
                           capture_output=True, text=True, env=env, cwd=str(ROOT))
        if not f.exists():
            raise RuntimeError("%s 没出结果：%s" % (step, (r.stderr or "")[-400:]))
        out[step] = json.loads(f.read_text(encoding="utf-8"))
    return out["drag"], out["reopen"]


def worst(drag, reopen):
    rows = []
    for name, a in drag["items"].items():
        b = reopen["items"].get(name)
        if not b:
            continue
        d = ((a["cx"] - b["cx"]) ** 2 + (a["cy"] - b["cy"]) ** 2) ** 0.5
        rows.append((d, name, a["side"], b["side"]))
    rows.sort(reverse=True)
    return rows


def main():
    tmp = Path(tempfile.mkdtemp(prefix="chklblpersist_"))
    (tmp / "covers").mkdir(exist_ok=True)
    for n in ("stations.json", "lines.json"):
        shutil.copy(ROOT / "data" / n, tmp / n)

    ok = bad = 0

    def chk(name, cond, detail):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  [OK]   %s\n         %s" % (name, detail))
        else:
            bad += 1
            print("  [FAIL] %s\n         %s" % (name, detail))

    print("=" * 74)
    print("手动调过的站名：关掉再打开，位置必须一模一样（拖 %s）" % DRAG_STATIONS)
    print("=" * 74)

    drag, reopen = run_pair(tmp, "normal")
    rows = worst(drag, reopen)
    if not rows:
        chk("A 拿到了拖动后/重开后的位置", False, "两步都没结果")
        return 1
    w = rows[0]
    chk("A 重开后位置零漂移（≤%.1fpx）" % TOL, w[0] <= TOL,
        "最大 %.1fpx（%s：拖动时 side=%s，重开 side=%s）"
        % (w[0], w[1], w[2], w[3]))

    # ---- B 变异自检 ----
    print("-" * 74)
    tmp2 = Path(tempfile.mkdtemp(prefix="chklblpersist_mut_"))
    (tmp2 / "covers").mkdir(exist_ok=True)
    for n in ("stations.json", "lines.json"):
        shutil.copy(ROOT / "data" / n, tmp2 / n)
    # ★★ 变异 = "拖动时**没把方位存下来**"。注意要在 **drag 落盘之后**再抹：
    #    光关 METROEDITOR_NO_LABEL_SIDE（只关写入、读取照旧）是假变异 ——
    #    真数据里 199/383 个站本来就有 label_side，读回来照样一致 ⇒ 0.0px。
    #    真身是"存的那一份丢了" ⇒ 重开退回 official_label_side（另一个方位）。
    def _strip_label_side(tmp):
        sp = tmp / "stations.json"
        d = json.loads(sp.read_text(encoding="utf-8"))
        st = d["stations"] if isinstance(d, dict) and "stations" in d else d
        for n in [s.strip() for s in DRAG_STATIONS.split(",")]:
            if isinstance(st.get(n), dict):
                st[n].pop("label_side", None)
        sp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    out = {}
    for step in ("drag", "reopen"):
        if step == "reopen":
            _strip_label_side(tmp2)
        f = tmp2 / ("mut_%s.json" % step)
        env = dict(os.environ)
        # ★ 开关只开在 **reopen** 那一步：drag 要照常（把方位存下来），
        #   否则 drag 自己就先退化成官方方位了，两边当然一模一样 ⇒ 变异又是假的。
        if step == "reopen":
            env["METROEDITOR_NO_LABEL_SIDE"] = "1"
        subprocess.run([PY, str(REPRO), "--step", step, "--data", str(tmp2),
                        "--out", str(f), "--drag", DRAG_STATIONS],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
        out[step] = json.loads(f.read_text(encoding="utf-8"))
    rows2 = worst(out["drag"], out["reopen"])
    w2 = rows2[0] if rows2 else (0.0, "-", "-", "-")
    print("  变异（drag 之后把存下来的 label_side 抹掉，重开只能退回官方方位）："
          "最大漂移 %.1fpx（%s：%s → %s）" % (w2[0], w2[1], w2[2], w2[3]))
    chk("B1 变异必须让 A 失败（判据真在岗）", w2[0] > TOL + 1.0,
        "变异最大 %.1fpx vs 现状 %.1fpx" % (w2[0], w[0]))

    print("-" * 74)
    print("通过 %d / 失败 %d" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
