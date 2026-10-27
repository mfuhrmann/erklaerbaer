# cluster_icons.py <pdf> <outdir> : group visually similar inline icons, write a contact sheet + JSON
import io, json, sys
import fitz
import numpy as np
from PIL import Image, ImageDraw

doc = fitz.open(sys.argv[1])
out = sys.argv[2]


def fingerprint(img):
    """Shape (16x16 grey, normalised) plus mean colour, size independent."""
    rgb = img.convert("RGB").resize((16, 16))
    a = np.asarray(rgb, dtype=float)
    grey = a.mean(axis=2)
    grey = (grey - grey.mean()) / (grey.std() + 1e-6)
    return grey.ravel(), a.reshape(-1, 3).mean(axis=0)


icons = {}  # digest -> {img, n, contexts}
for page in doc:
    words = page.get_text("words")
    for info in page.get_image_info(hashes=True, xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        if not (4 <= y1 - y0 <= 30 and x1 - x0 <= 40):
            continue
        key = info["digest"].hex()[:10]
        entry = icons.setdefault(key, {"n": 0, "contexts": []})
        entry["n"] += 1
        if "img" not in entry:
            pix = page.get_pixmap(clip=fitz.Rect(info["bbox"]), dpi=300)
            entry["img"] = Image.open(io.BytesIO(pix.tobytes("png")))
        if len(entry["contexts"]) < 2:
            mid = (y0 + y1) / 2
            line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - mid) < 5), key=lambda w: w[0])
            before = " ".join(w[4] for w in line if w[2] <= x0 + 1)[-50:]
            after = " ".join(w[4] for w in line if w[0] >= x1 - 1)[:50]
            entry["contexts"].append(f"S.{page.number + 1}: …{before} [■] {after}…")

keys = list(icons)
fp = {k: fingerprint(icons[k]["img"]) for k in keys}
clusters = []
for k in sorted(keys, key=lambda k: -icons[k]["n"]):
    shape, colour = fp[k]
    for c in clusters:
        s2, c2 = fp[c[0]]
        corr = float(np.dot(shape, s2) / len(shape))
        if corr > 0.80 and np.abs(colour - c2).max() < 40:
            c.append(k)
            break
    else:
        clusters.append([k])

report = []
tiles = []
for i, c in enumerate(clusters):
    n = sum(icons[k]["n"] for k in c)
    contexts = [ctx for k in c for ctx in icons[k]["contexts"]][:3]
    report.append({"gruppe": i, "digests": c, "vorkommen": n, "kontext": contexts})
    tile = Image.new("RGB", (120, 140), "white")
    im = icons[c[0]]["img"].convert("RGB")
    im.thumbnail((100, 100))
    tile.paste(im, (10, 5))
    ImageDraw.Draw(tile).text((5, 112), f"G{i} ({n}x)", fill="black")
    tiles.append(tile)

cols = 8
sheet = Image.new("RGB", (cols * 120, -(-len(tiles) // cols) * 140), "white")
for i, t in enumerate(tiles):
    sheet.paste(t, ((i % cols) * 120, (i // cols) * 140))
sheet.save(f"{out}/gruppen.png")
json.dump(report, open(f"{out}/gruppen.json", "w"), ensure_ascii=False, indent=1)
print(len(keys), "Bilddateien ->", len(clusters), "Gruppen")
