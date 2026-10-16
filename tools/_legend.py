from pathlib import Path
from PIL import Image
SRC = Path(__file__).resolve().parent.parent
ref = Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB")
im = ref.crop((160, 7300, 3500, 8000))
im.save(SRC / "_legend.png")
print("legend", im.size)
