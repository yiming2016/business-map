import json
from pathlib import Path
from PIL import Image
SRC = Path(__file__).resolve().parent.parent
ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
st = json.loads((SRC / "data/stations.json").read_text(encoding="utf-8"))["stations"]
for n in ["机场东", "后瑞", "固戍", "西乡", "坪洲"]:
    print(n, st[n]["x"], st[n]["y"], st[n]["lines"])
im = ref.crop((600, 2300, 2400, 3000))
im.save(SRC / "_s_L1west.png")
print("saved", im.size)
