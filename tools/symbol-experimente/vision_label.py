# vision_label.py <pdf> <hand.json> <out.json> : let a vision model name inline icons, compare with labels by hand
# Similar looking images (same icon in other sizes/backgrounds) are grouped, so the
# model looks at each icon once.
import base64, io, json, sys, time
from collections import Counter

import httpx
import numpy as np
import pymupdf
from PIL import Image

MODEL = "gemma3:4b"
doc = pymupdf.open(sys.argv[1])
manual = {d: w for w, ds in json.load(open(sys.argv[2], encoding="utf-8")).items() for d in ds}

icons = {}  # digest -> {"img", "area", "ctx"}
for page in doc:
    words = page.get_text("words")
    for info in page.get_image_info(hashes=True):
        x0, y0, x1, y1 = info["bbox"]
        if (y1 - y0) > 30 or (x1 - x0) > 45 or (y1 - y0) < 4:
            continue
        key = info["digest"].hex()[:10]
        mid = (y0 + y1) / 2
        line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - mid) < 4), key=lambda w: w[0])
        before = " ".join(w[4] for w in line if w[2] <= x0 + 1)[-70:]
        after = " ".join(w[4] for w in line if w[0] >= x1 - 1)[:70]
        if key not in manual and not (before and after):
            continue
        e = icons.setdefault(key, {"ctx": [], "area": 0})
        area = (x1 - x0) * (y1 - y0)
        if area > e["area"]:
            pix = page.get_pixmap(clip=pymupdf.Rect(info["bbox"]), dpi=400)
            e["img"], e["area"] = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"), area
        ctx = f"{before} [Symbol] {after}".strip()
        if (before or after) and ctx not in e["ctx"] and len(e["ctx"]) < 3:
            e["ctx"].append(ctx)


def fingerprint(img):
    a = np.asarray(img.resize((16, 16)), dtype=float)
    grey = a.mean(axis=2)
    return (grey - grey.mean()).ravel() / (grey.std() + 1e-6), a.reshape(-1, 3).mean(axis=0)


fp = {k: fingerprint(e["img"]) for k, e in icons.items()}
groups = []
for k in sorted(icons, key=lambda k: -icons[k]["area"]):
    for g in groups:
        s, c = fp[g[0]]
        if float(np.dot(fp[k][0], s) / 256) > 0.75 and np.abs(fp[k][1] - c).max() < 60:
            g.append(k)
            break
    else:
        groups.append([k])
print(f"{len(icons)} Bilddateien -> {len(groups)} Gruppen", flush=True)

PROMPT = ("Das Bild ist ein kleines Symbol aus der deutschen Anleitung eines Brettspiels. "
          "Es steht im Text an der Stelle [Symbol]:\n{ctx}\n\n"
          "Für welchen Spielbegriff steht das Symbol (z. B. eine Ressource, ein Kampfwert, eine Aktion)? "
          "Antworte nur mit dem Begriff, ein bis drei Wörter, auf Deutsch, wie er in der Anleitung heißen würde. "
          "Wenn es kein Spielsymbol ist (Bildausschnitt, Verzierung), antworte mit \"-\".")
labels = {}
started = time.time()
with httpx.Client(timeout=300) as client:
    for i, g in enumerate(groups):
        ctx = [c for k in g for c in icons[k]["ctx"]][:4]
        buf = io.BytesIO()
        icons[g[0]]["img"].save(buf, "PNG")
        t = time.time()
        r = client.post("http://localhost:11434/api/chat", json={
            "model": MODEL, "stream": False, "keep_alive": "2m",
            "options": {"temperature": 0, "num_predict": 16, "num_ctx": 2048},
            "messages": [{"role": "user", "content": PROMPT.format(ctx="\n".join(f"- {c}" for c in ctx) or "- (kein Text)"),
                          "images": [base64.b64encode(buf.getvalue()).decode()]}]}).json()
        label = r["message"]["content"].strip().strip(".\"„“")
        for k in g:
            labels[k] = label
        print(f"  G{i:02d} ({len(g)} Bilder) {time.time() - t:4.1f}s -> {label}"
              + (f"   [Hand: {manual[g[0]]}]" if g[0] in manual else ""), flush=True)
    client.post("http://localhost:11434/api/generate", json={"model": MODEL, "keep_alive": 0})
total = time.time() - started
print(f"{len(groups)} Anfragen in {total:.0f} s ({total / len(groups):.1f} s je Symbol)")
json.dump(labels, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)

both = [k for k in icons if k in manual]
right = [k for k in both if manual[k].lower() in labels[k].lower() or labels[k].lower() in manual[k].lower()]
print(f"Vergleich mit Hand-Zuordnung ({len(both)} Bilddateien): {len(right)} richtig")
for word in sorted(set(manual.values())):
    got = Counter(labels[k] for k in both if manual[k] == word)
    print(f"  {word:18} -> {dict(got.most_common(4))}")
