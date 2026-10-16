"""
tools/_shot_layout_compare.py
=============================
把「重排前 / 重排后」两张线路图并排渲染成一张对比图，供肉眼验收。

用法：
    python tools/_shot_layout_compare.py [旧stations.json] [新stations.json] [旧lines.json] [新lines.json]

要点：
- 画法**直接复用 tools/preview_map.py**（改模块属性后调它的 main()），
  不另抄一份画法 —— 否则"预览看到的"和"工具画的"可能对不上。
- 只读输入，**绝不写真数据**。
"""

import importlib.util
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SRC_ROOT = Path(__file__).resolve().parent.parent
PM = SRC_ROOT / "tools" / "preview_map.py"

DEFAULT = [
    SRC_ROOT / "data" / "stations.json.bak_relayout_20260929_045045",  # 重排前
    SRC_ROOT / "data" / "stations.json",                               # 重排后
    SRC_ROOT / "data" / "lines.json.bak",                              # 重排前（站序含"幛背"）
    SRC_ROOT / "data" / "lines.json",                                  # 重排后
]


def load_pm():
    spec = importlib.util.spec_from_file_location("preview_map", PM)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def render(pm, st_path, ln_path, out_png, size=1100):
    pm.STATIONS_PATH = Path(st_path)
    pm.LINES_PATH = Path(ln_path)
    pm.OUT = Path(out_png)
    pm.OUT_SIZE = size
    pm.K = size / pm.SCENE
    pm.main()
    return Image.open(out_png).convert("RGB")


def main():
    args = [Path(a) for a in sys.argv[1:]]
    paths = args + DEFAULT[len(args):]
    st_old, st_new, ln_old, ln_new = paths[:4]
    for p in (st_old, st_new, ln_old, ln_new):
        if not p.exists():
            print(f"[FAIL] 找不到输入文件: {p}")
            return 1

    pm = load_pm()
    SIZE = 1500
    tmp_dir = SRC_ROOT / "logs" / "_tmp_compare"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    img_old = render(pm, st_old, ln_old, tmp_dir / "old.png", SIZE)
    img_new = render(pm, st_new, ln_new, tmp_dir / "new.png", SIZE)

    BAR = 46
    GAP = 10
    W = SIZE * 2 + GAP
    H = SIZE + BAR
    canvas = Image.new("RGB", (W, H), (247, 249, 251))
    canvas.paste(img_old, (0, BAR))
    canvas.paste(img_new, (SIZE + GAP, BAR))

    d = ImageDraw.Draw(canvas)
    fnt = pm.get_font(22)
    d.text((14, 10), "改前 v2.6.16", fill=(30, 30, 30), font=fnt)
    d.text((SIZE + GAP + 14, 10), "改后 v2.6.17", fill=(200, 40, 40), font=fnt)

    out = SRC_ROOT / "logs" / "_layout_compare.png"
    canvas.save(out)
    print(f"[OK] 对比图已保存: {out}")
    print(f"    尺寸 {W}x{H}")
    print(f"    左 = {st_old.name} / {ln_old.name}")
    print(f"    右 = {st_new.name} / {ln_new.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
