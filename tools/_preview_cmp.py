import sys, json
from pathlib import Path
from PIL import Image
SRC = Path(__file__).resolve().parent.parent
ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
print("原图尺寸:", ref.size)
# 缩到宽 1400
W = 1400
ref_s = ref.resize((W, int(ref.height * W / ref.width)), Image.LANCZOS)
ref_s.save(SRC / "_p_ref.png")
for name in ["compare_new.png", "lines_new2.png", "lines_rounded.png"]:
    p = SRC / name
    if p.exists():
        im = Image.open(p).convert("RGB")
        im.thumbnail((1400, 1400), Image.LANCZOS)
        im.save(SRC / ("_p_" + name))
        print(name, "->", im.size)
