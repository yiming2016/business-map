# -*- coding: utf-8 -*-
"""v2.7.17 探针：看图模式"没改过就用上次那张"。

用户原话：「每次进入都要点击…生成图片，不能调用已经保存的信息吗？
如果检测没有更改过，采用已经保存的即可。」

三条改动：
 ① 缓存指纹 **文件修改时间 → 内容 md5**（旧判据必然每次失效：退出时
    无条件重写数据文件，mtime 必变）
 ② `dm.save()` 内容没变就**不写盘**（连 mtime 都不动）
 ③ 开软件**自动进看图模式**（`auto_on_start` 默认开；回归靠
    环境变量 `METROEDITOR_NO_VIEW_START=1` 屏蔽）
"""
import os
import sys
import time

# ★ 本探针自己要控制"什么时候进看图模式"，先屏蔽启动自动进入
os.environ["METROEDITOR_NO_VIEW_START"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import hashlib                                              # noqa: E402
import json                                                 # noqa: E402
import subprocess                                           # noqa: E402
import tempfile                                             # noqa: E402
from pathlib import Path                                    # noqa: E402

from PySide6.QtWidgets import QApplication                  # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402

app = QApplication(sys.argv)

from ui.main_window import MainWindow                       # noqa: E402
from ui import image_mode as IM                             # noqa: E402

FAILS = []
N_OK = 0


def ok(name, cond, info=""):
    global N_OK
    if cond:
        N_OK += 1
        print(f"  [OK] {name}" + (f"  —— {info}" if info else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  —— {info}" if info else ""))


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        QTest.qWait(10)


win = MainWindow()
win.resize(1400, 860)
win.show()
pump(25)
mv = win.map_view
d = win._data_dir()

# 清缓存，保证走"第一次"这条路径（v2.7.14 的教训）
for f in ("_view_image.png", "_view_image_meta.json"):
    p = Path(d) / f
    if p.exists():
        p.unlink()

# 统计真正烘了几次图
_real_render = IM.render_view_image
cnt = {"n": 0}


def spy_render(view, px=IM.PX_PER_UNIT):
    cnt["n"] += 1
    return _real_render(view, px)


IM.render_view_image = spy_render

# ======================================================================
print("===== ① 指纹 = 内容 md5（不是修改时间）=====")
sig0 = IM.signature(d)
ok("①-1 指纹算得出来", "stations.json:" in sig0 and "lines.json:" in sig0, sig0[:60] + "…")

# ★ 核心判据：只改 mtime、内容一字不动 ⇒ 指纹必须不变（旧实现这里必然变）
for n in ("stations.json", "lines.json"):
    p = Path(d) / n
    st = p.stat()
    os.utime(p, (st.st_atime + 7, st.st_mtime + 7))
sig1 = IM.signature(d)
ok("①-2 ★ 只改修改时间、内容没变 ⇒ 指纹不变（旧实现的病根）",
   sig1 == sig0, f"改时间前后 {'相同' if sig1 == sig0 else '不同！'}")

# 内容真变了 ⇒ 指纹必须变
with tempfile.TemporaryDirectory() as td:
    a = Path(td) / "stations.json"
    b = Path(td) / "lines.json"
    a.write_text('{"stations": {}}', encoding="utf-8")
    b.write_text('{"lines": []}', encoding="utf-8")
    s_before = IM.signature(td)
    a.write_text('{"stations": {"X": {}}}', encoding="utf-8")
    s_after = IM.signature(td)
    ok("①-3 内容真变了 ⇒ 指纹跟着变", s_before != s_after,
       f"{s_before[:28]}… → {s_after[:28]}…")

# ======================================================================
print("===== ② dm.save() 内容没变就别写盘 =====")
# ★ 预热一次：磁盘上可能是**旧格式**（老版本写出的字节/键顺序）跟内存里
#   规范化后的 dumps 不完全一致，那第一次 save 必然要写一次（这是"整理格式"，
#   不是用户改了东西）。判据测的是"稳定之后不该再写"。
win.dm.save()
pump(3)
sig_s = IM.signature(d)          # 稳定指纹，后面都以它为准
mt_before = {n: (Path(d) / n).stat().st_mtime_ns for n in ("stations.json", "lines.json")}
win.dm.save()          # 模拟"什么都没改就退出"
pump(3)
mt_after = {n: (Path(d) / n).stat().st_mtime_ns for n in ("stations.json", "lines.json")}
ok("②-1 ★ 没改东西 ⇒ save() 不动文件（mtime 都不变）",
   mt_before == mt_after,
   f"stations {mt_before['stations.json']} → {mt_after['stations.json']}")
ok("②-2 内容没变 ⇒ 指纹仍然不变", IM.signature(d) == sig_s)

# ======================================================================
print("===== ③ 缓存：第一次烘，之后直接读 =====")


def forget_mem():
    """★ 清掉**内存里的**那张图，才能验证"磁盘缓存"而不是"内存还留着"。

    不清的话 `_enter_view_mode` 看到 `self._view_img` 还在就直接用了，
    等于什么都没测（v2.7.17 第一次写探针就栽在这：③-5 假通过）。
    """
    win._view_img = None
    win._view_rect = None


forget_mem()
cnt["n"] = 0
t0 = time.time()
ok1 = win._enter_view_mode()
pump(20)
ok("③-1 第一次进看图模式成功", ok1 and mv._view_mode, f"耗时 {time.time()-t0:.1f}s")
ok("③-2 第一次确实烘了图", cnt["n"] == 1, f"烘图 {cnt['n']} 次")
ok("③-3 缓存文件已落地", (Path(d) / "_view_image.png").exists()
   and (Path(d) / "_view_image_meta.json").exists())
meta = json.loads((Path(d) / "_view_image_meta.json").read_text(encoding="utf-8"))
ok("③-4 meta 里存的是内容指纹", meta.get("sig") == sig_s, str(meta.get("sig"))[:40] + "…")
ok("③-4b 指纹对不上就**不**命中（不会拿错图）",
   IM.load_cache(d, "stations.json:deadbeef|lines.json:deadbeef", IM.PX_PER_UNIT) is None)

# 退出 → 再进（模拟"关了软件什么都没改，第二天再开"）
win._exit_view_mode()
pump(10)
win.dm.save()          # 退出时的那次 save
pump(3)
forget_mem()           # ★ 连内存那张也清掉，模拟"重新开软件"
cnt["n"] = 0
t1 = time.time()
ok2 = win._enter_view_mode()
pump(15)
ok("③-5 ★ 第二次进来**没有重新烘图**（用的是上次那张）", cnt["n"] == 0,
   f"烘图 {cnt['n']} 次，耗时 {time.time()-t1:.2f}s")
ok("③-6 第二次也成功进了看图模式", ok2 and mv._view_mode)
if cnt["n"] == 0:
    print(f"       （读缓存 {time.time()-t1:.2f}s vs 首次烘图 {time.time()-t0:.1f}s）")

# ======================================================================
print("===== ④ 变异自检：把指纹退回\"修改时间\"版，判据必须抓得住 =====")


def _old_signature(data_dir):
    """★ 变异版（v2.7.16 及以前的写法）：修改时间 + 大小。"""
    parts = []
    for name in ("stations.json", "lines.json"):
        p = Path(data_dir) / name
        try:
            st = p.stat()
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except Exception:
            parts.append(f"{name}:missing")
    return "|".join(parts)


_real_sig = IM.signature          # 先把真的存起来，变异完还原
win._exit_view_mode()
pump(10)
forget_mem()                      # ★ 同上：清内存，逼它去读磁盘缓存
IM.signature = _old_signature
try:
    p = Path(d) / "lines.json"
    st = p.stat()
    os.utime(p, (st.st_atime + 9, st.st_mtime + 9))    # 什么都没改，只是"重写了一遍"
    sig_old_a = IM.signature(d)
    os.utime(p, (st.st_atime + 19, st.st_mtime + 19))
    sig_old_b = IM.signature(d)
    ok("④-1 变异版：啥都没改，指纹却变了（旧病根复现）",
       sig_old_a != sig_old_b)
    cnt["n"] = 0
    win._enter_view_mode()
    pump(15)
    ok("④-2 ★ 变异版 ⇒ 缓存不命中、被迫重烘（判据确实抓得住）", cnt["n"] == 1,
       f"烘图 {cnt['n']} 次")
finally:
    IM.signature = _real_sig                     # 还原成真的（内容 md5）
    ok("④-3 变异已还原（指纹回到内容 md5）", IM.signature(d) == sig_s,
       f"{IM.signature(d)[:40]}…")

# ======================================================================
print("===== ⑤ 开软件自动进看图模式（auto_on_start 默认开）=====")
ok("⑤-1 默认设置里 auto_on_start = True",
   IM.DEFAULT_SETTINGS.get("auto_on_start") is True)
ok("⑤-2 用户配置里也是 True（旧的 False 已迁移）",
   IM.load_settings(d).get("auto_on_start") is True)
_src = Path(_ROOT) / "ui" / "main_window.py"
ok("⑤-3 源码里确有回归屏蔽分支 METROEDITOR_NO_VIEW_START",
   "METROEDITOR_NO_VIEW_START" in _src.read_text(encoding="utf-8"))

# 真跑一个子进程验证：不带屏蔽变量 ⇒ 启动后自动进看图模式
code = r'''
import os, sys
sys.path.insert(0, r"%s")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METROEDITOR_NO_ACTIVATE", "1")
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
app = QApplication(sys.argv)
from ui.main_window import MainWindow
win = MainWindow(); win.resize(1400, 860); win.show()
for _ in range(260):        # ≈2.6s，等 400ms 的 singleShot + 读缓存
    app.processEvents(); QTest.qWait(10)
print("CHILD view_mode =", getattr(win.map_view, "_view_mode", None))
''' % _ROOT
r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                   text=True, timeout=200,
                   env=dict(os.environ, METROEDITOR_NO_VIEW_START=""))
line = [l for l in r.stdout.splitlines() if l.startswith("CHILD")]
val = line[0] if line else f"无输出 / {r.stderr.strip()[-120:]}"
ok("⑤-4 ★ 开软件自动进了看图模式（不用点按钮）",
   "CHILD view_mode = True" in val, val)

# ======================================================================
print("===== ⑥ 首次烘图不再被看门狗误报「界面卡住」 =====")
try:
    import shutil
    import tempfile
    from core import watchdog
    # ★ 不能让"删不掉临时目录"伪装成一条 FAIL：watchdog 还开着那个日志文件
    #   （Windows 不让删），所以最后用 ignore_errors 兜着。
    td = tempfile.mkdtemp()
    try:
        lp = Path(td) / "err.log"
        watchdog.start(lp, stall_seconds=1.0)
        watchdog.hold(15.0, "测试：烘图")          # 声明在干重活
        watchdog._hb = time.perf_counter() - 5.0   # 假装心跳已经停了 5 秒
        time.sleep(2.0)                            # 等看门狗线程转两圈（阈值 1s）
        txt = lp.read_text(encoding="utf-8")
        ok("⑥-1 声明重活后，心跳停了也不报「卡住」",
           "卡住" not in txt, txt.strip().splitlines()[-1][:60])
        watchdog._hold_until = 0.0                 # 撤掉豁免
        watchdog._reported = False
        watchdog._hb = time.perf_counter() - 5.0
        time.sleep(2.0)
        txt2 = lp.read_text(encoding="utf-8")
        ok("⑥-2 ★ 变异自检：撤掉豁免后照样报警（判据真生效）",
           "卡住" in txt2, "已报")
    finally:
        shutil.rmtree(td, ignore_errors=True)
except Exception as e:
    ok("⑥ watchdog 豁免验证", False, repr(e))

print(f"\n===== 结果：{N_OK} 通过 / {len(FAILS)} 失败 =====")
if FAILS:
    for f in FAILS:
        print("   FAIL:", f)
sys.exit(1 if FAILS else 0)
