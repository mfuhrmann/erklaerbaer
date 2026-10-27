# unmapped.py <pdf> <mapping.json> <outdir> : images inside text lines that have no label yet
import io, json, sys
import pymupdf
from PIL import Image

doc = pymupdf.open(sys.argv[1])
known = {d for ds in json.load(open(sys.argv[2], encoding="utf-8")).values() for d in ds}
out = sys.argv[3]
found = {}
for page in doc:
    words = page.get_text("words")
    for info in page.get_image_info(hashes=True):
        key = info["digest"].hex()[:10]
        if key in known:
            continue
        x0, y0, x1, y1 = info["bbox"]
        if (y1 - y0) > 40 or (x1 - x0) > 60:
            continue
        mid = (y0 + y1) / 2
        line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - mid) < 4), key=lambda w: w[0])
        before = [w[4] for w in line if w[2] <= x0 + 1 and x0 - w[2] < 25]
        after = [w[4] for w in line if w[0] >= x1 - 1 and w[0] - x1 < 25]
        if not (before or after):
            continue  # not inside running text
        e = found.setdefault(key, {"n": 0, "ctx": []})
        e["n"] += 1
        if len(e["ctx"]) < 2:
            l = " ".join(w[4] for w in line if w[2] <= x0 + 1)[-45:]
            r = " ".join(w[4] for w in line if w[0] >= x1 - 1)[:45]
            e["ctx"].append(f"S.{page.number + 1}: …{l} [■] {r}…")
        if "png" not in e:
            page.get_pixmap(clip=pymupdf.Rect(info["bbox"]), dpi=300).save(f"{out}/u-{key}.png")
            e["png"] = True
for k, e in sorted(found.items(), key=lambda x: -x[1]["n"]):
    print(f"{k} {e['n']:3d}x  {' || '.join(e['ctx'])}"[:230])
