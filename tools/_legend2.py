from pathlib import Path
import numpy as np
from PIL import Image
SRC = Path(__file__).resolve().parent.parent
full = np.array(Image.open(SRC / "assets" / "shenzhen_metro.png").convert("RGB"))
def probe(cx, cy, x0=160, y0=7280):
    sub = full[y0+cy-30:y0+cy+30, x0+cx-100:x0+cx+100].reshape(-1,3).astype(int)
    mx=sub.max(axis=1); mn=sub.min(axis=1)
    keep=(mx-mn>18)&(mx<250)
    if keep.sum()<50: return None,0
    sel=sub[keep]; c=np.median(sel,axis=0).astype(int)
    return "#%02X%02X%02X"%tuple(int(v) for v in c), int(keep.sum())
for name,cx,cy in [("9号线",2614,241),("12号线",1615,357),("13号线",2114,357),
                   ("14号线",2614,357),("有轨电车",1615,474),("坪山云巴",2114,474)]:
    print(name, probe(cx,cy))
