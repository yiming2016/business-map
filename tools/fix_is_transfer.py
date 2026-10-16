# -*- coding: utf-8 -*-
"""把 `is_transfer` 与 `lines` 对齐（幂等，可反复跑）。

背景：v2.6.18 按官方图修拓扑时给几个站**加了线路**（湖贝 2→2/5、红岭南 9→9/11、
福田口岸 4→4/10、清湖 4→4/有轨电车、坪山云巴相关），但 `is_transfer` 没跟着改。
`metro_render` 是靠这个字段决定"画普通圆点还是换乘药丸"的 ⇒ 这几站在图上
**明明是换乘站却画成了普通小圆点**（用户一眼能看出来的错）。

规则（与 `core/schema.derive_is_transfer` 完全一致）：`is_transfer = len(lines) > 1`

★ 改的是 `源码/data/stations.json`；**跑之前必须先关掉 exe**（不然会被内存里的
  旧数据覆盖回去）。两份 data（源码/data 与 软件/data）要手工同步。

用法：
    python tools/fix_is_transfer.py           # 只改内存并打印
    python tools/fix_is_transfer.py --write   # 落盘（会先备份 .bak_is_transfer_<时间>）
"""
import json
import sys
import shutil
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent


def main(write: bool) -> int:
    p = SRC / "data" / "stations.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    st = doc.get("stations") or {}
    changed = []
    for name, s in st.items():
        lines = s.get("lines") or []
        want = len(lines) > 1
        if bool(s.get("is_transfer")) != want:
            changed.append((name, s.get("lines"), s.get("is_transfer"), want))
            s["is_transfer"] = want
    print("不一致 %d 处：" % len(changed))
    for n, l, old, new in changed:
        print("  %-8s lines=%-22s is_transfer %s → %s" % (n, l, old, new))
    if not changed:
        print("  （无，数据已经一致）")
        return 0
    if not write:
        print("\n未落盘。确认无误后加 --write")
        return 0
    bak = p.with_suffix(p.suffix + ".bak_is_transfer_" + time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(p, bak)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已写入 %s\n备份 %s" % (p, bak.name))
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
