# -*- coding: utf-8 -*-
"""一次性清理脚本：把工程里的无用文件移入 _backup/_trash_<date>/，不直接删除。

分类原则：
  - 移走：缓存、调试图、诊断产物、历史 .bak、调试 json/txt
  - 保留：运行必需的源码 / assets / data 核心 json / _backup / tools / 软件(exe+data+error.log)
"""
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent          # .../源码
ROOT = SRC.parent                                     # .../subway
SOFT = ROOT / "软件"
TRASH = SRC / "_backup" / "_trash_20260918"

moved = []          # (原路径, 大小)
skipped = []


def move(p: Path, bucket: str):
    """把 p 移到 TRASH/<bucket>/ 下，保留文件名。"""
    if not p.exists():
        skipped.append((p, "不存在"))
        return
    if "_backup" in p.parts:
        skipped.append((p, "位于 _backup，跳过"))
        return
    size = p.stat().st_size if p.is_file() else sum(
        f.stat().st_size for f in p.rglob("*") if f.is_file())
    dest_dir = TRASH / bucket
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / p.name
    if dest.exists():
        dest = dest_dir / (p.stem + "_dup" + p.suffix)
    shutil.move(str(p), str(dest))
    moved.append((p, size))


# ---------- A. Python 缓存 ----------
move(SRC / "__pycache__", "源码根")

# ---------- B. 源码根目录：下划线开头的调试图片 ----------
for p in sorted(SRC.glob("_*.png")):
    move(p, "源码根")

# ---------- C. 源码根目录：下划线开头的调试文本/json ----------
for pat in ("_*.txt", "_*.json", "_*.csv", "_*.log"):
    for p in sorted(SRC.glob(pat)):
        move(p, "源码根")

# ---------- D. 源码根目录：命名调试图片（非下划线开头） ----------
NAMED_DEBUG = [
    "cmp_zoom.png", "compare.png", "compare_new.png", "gui_shot.png",
    "lines_new.png", "lines_new2.png", "lines_octi.png", "lines_rounded.png",
    "lines_smooth.png", "markers_vis.png", "ov_zoom.png", "overlay.png",
    "overlay2.png", "preview.png", "ref_small.png", "shot_fit.png",
    "snap_vis.png", "zoom1.png",
]
for n in NAMED_DEBUG:
    move(SRC / n, "源码根")

# ---------- E. 源码/_tiles 调试瓦片 ----------
move(SRC / "_tiles", "源码根")

# ---------- F. 软件/logs 诊断产物（保留 error.log 与该目录） ----------
for p in sorted((SOFT / "logs").glob("*.png")):
    move(p, "软件logs")
for p in sorted((SOFT / "logs").glob("*.npy")):
    move(p, "软件logs")
for n in ("e2e_frames", "zoomseq"):
    move(SOFT / "logs" / n, "软件logs")

# ---------- G. 源码/data 调试产物（保留 lines/stations/schema 及 .bak 基线） ----------
for p in sorted((SRC / "data").glob("_snap_check*.png")):
    move(p, "源码data")
for p in sorted((SRC / "data").glob("_*.json")):
    move(p, "源码data")
for p in sorted((SRC / "data").glob("_*.txt")):
    move(p, "源码data")
# 带版本号的历史备份（保留无后缀的 .bak 基线）
for p in sorted((SRC / "data").glob("*.bak_*")):
    move(p, "源码data")

# ---------- 汇总 ----------
total = sum(s for _, s in moved)
print(f"已移入回收站：{TRASH}")
print(f"    对象 {len(moved)} 项，合计 {total / 1024 / 1024:.2f} MB")
print()
by_bucket = {}
for p, s in moved:
    by_bucket.setdefault(p.parent.name if p.is_file() else "<目录>", [0, 0])
for p, s in moved:
    key = str(p.parent.relative_to(ROOT))
    by_bucket.setdefault(key, [0, 0])
    by_bucket[key][0] += 1
    by_bucket[key][1] += s
for k, (c, s) in sorted(by_bucket.items()):
    print(f"    {k:<24} {c:>4} 项  {s / 1024 / 1024:>8.2f} MB")

if skipped:
    print("\n跳过：")
    for p, r in skipped:
        print(f"    {p}  ({r})")
