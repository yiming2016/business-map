# -*- coding: utf-8 -*-
"""v2.6.79：封面图 → 多图 的一次性迁移。

把每站旧的 `cover`（单张文件名）写进新的 `images` 列表第一张：
    images 缺失/为空 且 cover 非空  ⇒  images = [cover]
cover 字段保留不动（兼容旧读路径），幂等：跑多少遍结果一致。

用法（在源码目录下）：
    python tools/migrate_images_field.py            # 先 --dry 看清单
    python tools/migrate_images_field.py --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.data_manager import get_data_manager  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv
    dm = get_data_manager()
    stations = dm.stations_doc["stations"]
    changed = []
    for sid, rec in stations.items():
        imgs = rec.get("images")
        cov = (rec.get("cover") or "").strip()
        if (not imgs) and cov:
            changed.append((sid, cov))
            rec["images"] = [cov]
    print(f"待迁移 {len(changed)} 站")
    for sid, cov in changed[:20]:
        print(f"  {sid}: cover={cov} -> images=[{cov}]")
    if len(changed) > 20:
        print(f"  … 其余 {len(changed) - 20} 站略")
    if apply:
        dm.save()
        print("已落盘（dm.save）")
    else:
        print("（dry run，加 --apply 才写盘）")


if __name__ == "__main__":
    main()
