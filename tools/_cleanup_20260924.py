# -*- coding: utf-8 -*-
"""
2026-09-24 清理（第二轮）：把排查「保存/导入时崩溃」用的一次性二分脚本
移入 _backup 回收站。根因与回归都已沉淀进 tools/_chk_geom_change_order.py。

为什么只动这 4 个（而不是全部 26 个"无人引用"的脚本）：
    那 26 个是用"文件名有没有被别人提到"这个粗糙规则筛出来的。
    其中有些虽然没被点名，却是**重要结论的唯一出处**——
    例如 `_probe_layout_cost.py` 就是 README 里"379 站站名排版 97~109ms"
    那个数字的测量脚本。这种不能凭"没人提"就搬走。

    下面这 4 个则是**我这一轮刚收尾、且已被更新的工具取代**的：
      _shot_v254.py / _shot_v254_cmp.py  → v2.5.4 的"改前改后对照出图"，
                                           现由 _chk_zoom_anchor_realvp.py
                                           等定量脚本取代（出图只是旁证）
      _crop_missing.py                   → 针对 6 个具体站名的裁图助手，一次性
      _diag4.py                          → 编号诊断脚本，一次性

移动而不是删除；回收站里配了 回滚.py，随时可还原。
用法：python tools/_cleanup_20260924.py            # 只报告（默认）
      python tools/_cleanup_20260924.py --apply    # 真正移动
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
TOOLS = SRC / "tools"
TRASH = SRC / "_backup" / "_trash_20260924_repro"

TARGETS = [
    ("_repro_crash.py", "崩溃最小复现（已由 _chk_geom_change_order.py 取代）"),
    ("_repro2.py", "崩溃二分：隐藏 vs 隔离标志"),
    ("_repro3.py", "崩溃二分：_apply_isolation 拆成单步（定位到 S6）"),
    ("_repro4.py", "崩溃二分：S6 内部（定位到 set_label_side）"),
    ("_repro5.py", "崩溃二分：单图元级别"),
    ("_repro6.py", "崩溃二分：缓存 / 场景索引 / 数量阈值"),
    ("_repro7.py", "崩溃二分：删除后场景残留 + paintEvent 打点"),
    ("_repro8.py", "崩溃二分：全局事件过滤器记崩溃前事件"),
    ("_repro9.py", "崩溃二分：processEvents 各步骤（定位到渲染）"),
    ("_repro10.py", "崩溃二分：场景索引 BSP 假说（NoIndex 不崩）"),
    ("_repro11.py", "纯 PySide6 最小复现（不依赖本项目）"),
    ("_repro12.py", "纯 PySide6 + 逐个加渲染开关"),
    ("_repro13.py", "对全部 379 图元只做一种动作（定位到 set_label_side）"),
    ("_repro14.py", "崩溃点追踪（场景清空照样崩）"),
    ("_repro15.py", "无害操作探测（viewport().grab() 必崩）"),
    ("_repro16.py", "各种清理手段尝试（setScene(None) 不崩）"),
    ("_repro17.py", "★ 根因验证：prepareGeometryChange 提前就不崩"),
]

ROLLBACK = '''# -*- coding: utf-8 -*-
"""回滚：把 2026-09-24 移入回收站的脚本搬回 源码/tools/。

用法：python 回滚.py            # 只报告
      python 回滚.py --apply    # 真正搬回
"""
import argparse, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"          # _backup/_trash_.../ → 源码/tools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    files = sorted(p for p in HERE.iterdir() if p.suffix == ".py" and p.name != "回滚.py")
    if not files:
        print("回收站里没有可回滚的文件")
        return 0
    for p in files:
        dst = TOOLS / p.name
        if a.apply:
            if dst.exists():
                print("跳过（tools 里已存在同名文件）：%s" % p.name)
                continue
            shutil.move(str(p), str(dst))
            print("已还原：%s" % p.name)
        else:
            print("将还原：%s  →  %s" % (p.name, dst))
    if not a.apply:
        print("\\n（确认无误后加 --apply 真还原）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正移动（默认只报告）")
    args = ap.parse_args()

    exist = [(n, why) for n, why in TARGETS if (TOOLS / n).exists()]
    missing = [n for n, _ in TARGETS if not (TOOLS / n).exists()]

    print("回收站目录：%s" % TRASH)
    print("待移动 %d 个：" % len(exist))
    for n, why in exist:
        print("   %-24s %s  (%.1f KB)" % (n, why, (TOOLS / n).stat().st_size / 1024))
    if missing:
        print("已在别处/不存在（跳过）：%s" % missing)

    if not args.apply:
        print("\n（这是只报告模式；确认无误后加 --apply 真移动）")
        return 0

    TRASH.mkdir(parents=True, exist_ok=True)
    moved = 0
    for n, _ in exist:
        dst = TRASH / n
        if dst.exists():
            print("跳过（回收站已存在）：%s" % n)
            continue
        shutil.move(str(TOOLS / n), str(dst))
        moved += 1
    (TRASH / "回滚.py").write_text(ROLLBACK, encoding="utf-8")

    print("\n已移入回收站：%d 个 → %s" % (moved, TRASH))
    print("回滚：cd \"%s\" && python 回滚.py --apply" % TRASH)
    # 复核
    left = [n for n, _ in TARGETS if (TOOLS / n).exists()]
    print("复核：tools/ 里还剩 %d 个（应为 0）%s" % (len(left), left))
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
