import numpy as np, json
from pathlib import Path
from PIL import Image
SRC = Path(__file__).resolve().parent.parent
ref = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))
st = json.loads((SRC / "data/stations.json").read_text(encoding="utf-8"))["stations"]

def crop(name, half=110):
    s = st[name]; x, y = int(s["x"]), int(s["y"])
    x0, x1 = max(0, x-half), min(8000, x+half)
    y0, y1 = max(0, y-half), min(8000, y+half)
    im = Image.fromarray(ref[y0:y1, x0:x1])
    im = im.resize((im.width*3, im.height*3), Image.NEAREST)
    out = SRC / f"_c_{name}.png"
    im.save(out); print(name, (x,y), "->", out)

for n in ["燕南", "机场东", "老街", "车公庙"]:
    crop(n)
