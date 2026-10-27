# scan_icons.py <pdf>... : count small images that sit inside running text lines
import os, sys
import pymupdf

print(f"{'Spiel':42} {'Seiten':>6} {'Symbole':>8} {'versch.':>7}")
rows = []
for path in sys.argv[1:]:
    doc = pymupdf.open(path)
    n, digests = 0, set()
    for page in doc:
        words = page.get_text("words")
        if not words:
            continue
        for info in page.get_image_info(hashes=True):
            x0, y0, x1, y1 = info["bbox"]
            if (y1 - y0) > 30 or (x1 - x0) > 45 or (y1 - y0) < 4:
                continue
            mid = (y0 + y1) / 2
            line = [w for w in words if abs((w[1] + w[3]) / 2 - mid) < 4]
            if any(w[2] <= x0 + 1 and x0 - w[2] < 25 for w in line) or any(w[0] >= x1 - 1 and w[0] - x1 < 25 for w in line):
                n += 1
                digests.add(info["digest"])
    rows.append((n, os.path.basename(path)[:-4], len(doc), len(digests)))
for n, name, pages, d in sorted(rows, reverse=True):
    if n:
        print(f"{name:42} {pages:6d} {n:8d} {d:7d}")
print(f"{sum(1 for r in rows if r[0] == 0)} Regelhefte ohne Symbole im Fließtext")
