# -*- coding: utf-8 -*-
"""
_cleanup_20260924_shot.py —— 只清理**本轮（v2.6.1 卡片修复）我自己刚做、且已被更新
的工具取代**的那几张临时截图。

背景：`源码/logs/` 长期被当作验收截图的堆放处，里面有几十张历史图（几 MB）。
按项目约定（见 MEMORY.md §2）：
  · 只清理"本轮刚做完、已被更新工具取代"的；
  · 其余**列清单交给用户定**，不擅自搬。
  · 一律**移入回收站**（配 `回滚.py`），不直接删。

本轮要清的 4 张，都是我为"看细节"临时裁切/缩放出来的，原始图仍在
（`_iso_3.png` / `_iso_11.png` / `_iso_10.png` / `_running_exe.png` 由工具生成，保留）：
    logs/_card_3.png        裁切自 _iso_3.png
    logs/_card_11.png       裁切自 _iso_11.png
    logs/_iso_3_small.png   缩放自 _iso_3.png
    logs/_running_small.png 缩放自 _running_exe.png

用法：
    python tools/_cleanup_20260924_shot.py            # 只报告，不动任何文件
    python tools/_cleanup_20260924_shot.py --apply    # 真的移入回收站
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
LOGS = SRC / "logs"
TRASH = SRC / "_backup" / "_trash_20260924_shot"

TARGETS = [
    "logs/_card_3.png",
    "logs/_card_11.png",
    "logs/_iso_3_small.png",
    "logs/_running_small.png",
]

# 明确"不碰"的（工具生成、可复现、README 里有说明）
KEEP = [
    "logs/_iso_3.png", "logs/_iso_10.png", "logs/_iso_11.png",
    "logs/_running_exe.png",
]

ROLLBACK = '''# -*- coding: utf-8 -*-
"""回滚：把本轮移走的 4 张临时截图搬回 源码/logs/。

    python 回滚.py            # 只报告
    python 回滚.py --apply    # 真搬回
"""
import argparse, json, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent.parent          # _backup/_trash_xxx → 源码
MAN = HERE / "清单.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    items = json.loads(MAN.read_text(encoding="utf-8"))
    n = 0
    for it in items:
        back = SRC / it["原路径"]
        if (HERE / it["回收站名"]).exists() and not back.exists():
            print("  搬回 %s" % it["原路径"])
            if a.apply:
                back.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(HERE / it["回收站名"]), str(back))
            n += 1
    print("共 %d 个%s" % (n, "（已搬回）" if a.apply else "（试运行，未动）"))


if __name__ == "__main__":
    main()
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    todo = []
    for rel in TARGETS:
        p = SRC / rel
        if p.exists():
            todo.append((rel, p))
        else:
            print("  [跳过] 不存在：%s" % rel)

    print("轮次：v2.6.1 卡片修复")
    print("回收站：%s" % TRASH)
    print("将要移入 %d 个文件。" % len(todo))
    for rel, p in todo:
        print("    %-26s %8d 字节" % (rel, p.stat().st_size))

    print("\n保留（工具生成、可复现）：")
    for rel in KEEP:
        p = SRC / rel
        print("    %-26s %s" % (rel, "在" if p.exists() else "（不在）"))

    # 其余历史截图只列数量，交给用户定
    others = [p for p in LOGS.glob("*.png")
              if ("logs/" + p.name) not in TARGETS
              and ("logs/" + p.name) not in KEEP]
    if others:
        total = sum(p.stat().st_size for p in others)
        print("\n★ 另有 %d 张历史截图（共 %.1f MB）**未动** —— 需要清理请单独说。"
              % (len(others), total / 1024 / 1024))
        print("  最早/最新：%s / %s"
              % (min(p.name for p in others), max(p.name for p in others)))

    if not args.apply:
        print("\n[试运行] 未移动任何文件。加 --apply 才真移。")
        return 0

    TRASH.mkdir(parents=True, exist_ok=True)
    man = []
    n = 0
    for rel, p in todo:
        dst = TRASH / Path(rel).name
        if dst.exists():                      # 撞名加时间戳，绝不覆盖
            dst = TRASH / ("%s.%s" % (p.stem, datetime.now().strftime("%H%M%S")))
            dst = dst.with_suffix(p.suffix)
        shutil.move(str(p), str(dst))
        man.append({"原路径": rel, "回收站名": dst.name})
        n += 1

    (TRASH / "清单.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    (TRASH / "回滚.py").write_text(ROLLBACK, encoding="utf-8")

    # 复核：移完之后源目录里确实 0 个
    left = [rel for rel, _ in todo if (SRC / rel).exists()]
    print("\n已移入 %d 个；复核源目录剩余 %d 个（应为 0）" % (n, len(left)))
    print("回滚：cd %s && python 回滚.py --apply" % TRASH)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
