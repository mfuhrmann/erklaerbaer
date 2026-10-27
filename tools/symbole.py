"""Inline icons in rulebooks: find them, and put their meaning in as invisible text.

Rulebooks print values like strength or blood as small pictures inside the
sentence ("Jedes <Blut> eines Klans tötet 1 Truppe"). Text extraction drops
them, and the sentence loses its point (Gunsen: 0/5 right answers without,
5/5 with). Neither the LLM (from context) nor a small vision model could name
them reliably, so a person names them once per rulebook in the gallery on the
web page (/symbole).

Icons are found on the rendered page, not as PDF objects: where a text line
has a gap, where a line starts or ends next to a drawing, or where a table
cell has no text, the spot is rendered; if something is drawn there that
stays inside the spot, it is an icon. This works for embedded images
(Gunsen), vector drawings (Cena) and pictures cut into hundreds of tiles
(7 Wonders Duel) alike.

    find_symbols(pdf)               groups of similar icons with their places
    annotate(pdf, placements, out)  writes "[Blut]" invisibly onto each place
"""
import sys

import pymupdf

RENDER_DPI = 110      # for finding ink; enough for icons of 8 pt and more
GAP = 0.45            # gap (in word-box heights, which include ascenders and
                      # descenders, ~1.6x the font size) that may hold an icon; a space is ~0.15
SIDE = 2.2            # how far (in line heights) to look before/after a line
INK = 70              # colour distance from the background that counts as ink


def ink_box(page, rect, words=(), open_sides=""):
    """Bounding box of what is drawn in rect, not counting text, or None.

    Also None if the drawing touches an edge of rect: then it is part of
    something bigger (a frame, a picture, the next column). Edges listed in
    open_sides ("l", "r") may be touched: a gap between two words is often a
    little narrower than the icon in it.
    """
    rect = rect & page.rect
    if rect.is_empty or rect.width < 2 or rect.height < 2:
        return None
    pix = page.get_pixmap(clip=rect, dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
    w, h, s = pix.width, pix.height, pix.samples
    if w < 4 or h < 4:
        return None
    scale = rect.width / w
    # Text in the spot (neighbouring lines, the words beside a gap) is no icon.
    text = [((r.x0 - rect.x0) / scale, (r.y0 - rect.y0) / scale, (r.x1 - rect.x0) / scale, (r.y1 - rect.y0) / scale)
            for r in (pymupdf.Rect(wd[:4]) for wd in words) if r.intersects(rect)]
    in_text = lambda x, y: any(a <= x <= c and b <= y <= d for a, b, c, d in text)
    px = lambda x, y: s[3 * (y * w + x):3 * (y * w + x) + 3]
    edge = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    border = [px(x, y) for x, y in edge if not in_text(x, y)]
    if not border:
        return None
    # Median per channel: robust against textured paper and bits of drawings.
    bg = [sorted(p[c] for p in border)[len(border) // 2] for c in range(3)]
    xs, ys = [], []
    for y in range(h):
        row = s[3 * y * w:3 * (y + 1) * w]
        masked = [(a, c) for a, b, c, d in text if b <= y <= d]
        for x in range(w):
            if any(a <= x <= c for a, c in masked):
                continue
            r, g, b = row[3 * x:3 * x + 3]
            if abs(r - bg[0]) > INK or abs(g - bg[1]) > INK or abs(b - bg[2]) > INK:
                xs.append(x)
                ys.append(y)
    if len(xs) < max(6, 0.03 * w * h):
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if y0 == 0 or y1 == h - 1 or (x0 == 0 and "l" not in open_sides) or (x1 == w - 1 and "r" not in open_sides):
        return None
    return pymupdf.Rect(rect.x0 + x0 * scale, rect.y0 + y0 * scale,
                        rect.x0 + (x1 + 1) * scale, rect.y0 + (y1 + 1) * scale)


def candidates(page):
    """(spot, line height, words left, words right, in a table, open sides) where an icon may sit."""
    words = page.get_text("words")
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    spots = []

    def free(rect):
        return not any(pymupdf.Rect(w[:4]).intersects(rect) for w in words)

    for line in lines.values():
        line.sort(key=lambda w: w[0])
        top, bottom = min(w[1] for w in line), max(w[3] for w in line)
        h = bottom - top
        # Icons are often taller than the text; neighbouring lines in the
        # spot don't matter, text is masked out (ink_box).
        pad = 0.6 * h
        texts = [w[4] for w in line]
        for i in range(len(line) - 1):
            gap = line[i + 1][0] - line[i][2]
            if gap > GAP * h:
                spots.append((pymupdf.Rect(line[i][2] + 0.05 * h, top - pad, line[i + 1][0] - 0.05 * h, bottom + pad),
                              h, texts[:i + 1], texts[i + 1:], False, "lr"))
        before = pymupdf.Rect(line[0][0] - SIDE * h, top - pad, line[0][0] - 0.05 * h, bottom + pad)
        if free(before):
            spots.append((before, h, [], texts, False, "r"))
        after = pymupdf.Rect(line[-1][2] + 0.05 * h, top - pad, line[-1][2] + SIDE * h, bottom + pad)
        if free(after):
            spots.append((after, h, texts, [], False, "l"))
    # Table cells without text, e.g. a column of icons in a setup table.
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    for table in tables:
        for row in table.rows:
            row_text = [w[4] for w in words if row.bbox[1] <= (w[1] + w[3]) / 2 <= row.bbox[3]
                        and table.bbox[0] <= w[0] <= table.bbox[2]]
            for cell in row.cells:
                if cell is None:
                    continue
                inner = pymupdf.Rect(cell) + (2, 2, -2, -2)
                if free(inner):
                    spots.append((inner, inner.height, row_text, [], True, ""))
    return spots


def fingerprint(page, rect):
    """Shape (16x16 grey, normalised) and mean colour, independent of size."""
    pix = pymupdf.Pixmap(page.get_pixmap(clip=rect, dpi=200, colorspace=pymupdf.csRGB, alpha=False), 16, 16)
    s = pix.samples
    pixels = [s[i:i + 3] for i in range(0, len(s), 3)][:256]
    grey = [sum(p) / 3 for p in pixels]
    mean = sum(grey) / len(grey)
    spread = (sum((g - mean) ** 2 for g in grey) / len(grey)) ** 0.5 + 1e-6
    colour = [sum(p[c] for p in pixels) / len(pixels) for c in range(3)]
    return [(g - mean) / spread for g in grey], colour


def similar(a, b):
    # Strict: one name per group, so a group must never mix two icons. A few
    # extra groups (same icon on another background) cost one more input.
    shape = sum(x * y for x, y in zip(a[0], b[0])) / len(a[0])
    return shape > 0.9 and max(abs(x - y) for x, y in zip(a[1], b[1])) < 25


def image_icons(page):
    """(digest, rect) of icon-sized embedded images.

    Touching small images are joined first: some rulebooks build an icon from
    several overlapping images, others cut big pictures into tiles. An
    icon-sized result is an icon (digest of its largest part), a big one not.
    """
    parts = [(pymupdf.Rect(i["bbox"]), i["digest"].hex()[:10]) for i in page.get_image_info(hashes=True)]
    parts = [p for p in parts if p[0].width < 100 and p[0].height < 100]  # not backgrounds
    group = list(range(len(parts)))

    def root(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for i, (a, _) in enumerate(parts):
        grown = a + (-1, -1, 1, 1)
        for j in range(i + 1, len(parts)):
            if grown.intersects(parts[j][0]):
                group[root(i)] = root(j)
    units = {}
    for i, part in enumerate(parts):
        units.setdefault(root(i), []).append(part)
    icons = []
    for members in units.values():
        rect = pymupdf.Rect(members[0][0])
        for r, _ in members[1:]:
            rect |= r
        if 4 <= rect.height <= 30 and rect.width <= 45:
            icons.append((max(members, key=lambda m: m[0].width * m[0].height)[1], rect))
    return icons


def words_beside(words, box):
    """Words on the same line just left and right of box."""
    mid = (box.y0 + box.y1) / 2
    line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - mid) < 4), key=lambda w: w[0])
    left = [w[4] for w in line if w[2] <= box.x0 + 1]
    right = [w[4] for w in line if w[0] >= box.x1 - 1]
    near = (left and box.x0 - max(w[2] for w in line if w[2] <= box.x0 + 1) < 25) or \
           (right and min(w[0] for w in line if w[0] >= box.x1 - 1) - box.x1 < 25)
    return (left, right) if near else ([], [])


def example_text(left, right):
    return f"…{' '.join(left)[-60:]} ■ {' '.join(right)[:60]}…"


def find_symbols(pdf_path):
    """Groups of similar icons, most frequent first.

    Each group: {"places": [[page, x0, y0, x1, y1], ...], "count": n,
    "examples": [text with ■, ...], "png": image of the largest occurrence}.
    """
    doc = pymupdf.open(pdf_path)
    found = []  # (key, fingerprint, page, rect, example); key: image digest or None
    for page in doc:
        words = page.get_text("words")
        seen = []
        # 1. Embedded images (also icons built from several overlapping images).
        for key, box in image_icons(page):
            left, right = words_beside(words, box)
            if left or right:
                seen.append(box)
                found.append((key, fingerprint(page, box), page.number, box, example_text(left, right)))
        # 2. Drawn on the page where text leaves a gap (vector icons, tiled pictures).
        for spot, h, left, right, in_table, open_sides in candidates(page):
            box = ink_box(page, spot, words, open_sides)
            if box is None:
                continue
            # Icon sized: about as high as the text (up to a little taller);
            # a table cell may hold several icons side by side.
            if not in_table and not (0.3 * h <= box.height <= 1.8 * h and box.width <= 3.2 * max(h, box.height)):
                continue
            if (in_table and box.height < 6) or any(box.intersects(other) for other in seen):
                continue
            seen.append(box)
            found.append((None, fingerprint(page, box), page.number, box, example_text(left, right)))

    groups = []
    for key, prints, number, box, example in sorted(found, key=lambda f: -f[3].width * f[3].height):
        # The same image is the same icon; otherwise compare how they look.
        group = next((g for g in groups if key and key in g["keys"]), None) \
            or next((g for g in groups if similar(prints, g["print"])), None)
        if group is None:
            pix = doc[number].get_pixmap(clip=box, dpi=300)
            group = {"print": prints, "keys": set(), "places": [], "count": 0, "examples": [], "png": pix.tobytes("png")}
            groups.append(group)
        if key:
            group["keys"].add(key)
        group["places"].append([number, round(box.x0, 2), round(box.y0, 2), round(box.x1, 2), round(box.y1, 2)])
        group["count"] += 1
        if len(group["examples"]) < 3 and example not in group["examples"]:
            group["examples"].append(example)
    for group in groups:
        del group["print"], group["keys"]
    return sorted(groups, key=lambda g: -g["count"])


def names_from_digests(pdf_path, groups, mapping):
    """Group index -> name, from an older mapping of image digests to names."""
    doc = pymupdf.open(pdf_path)
    named = {d: word for word, digests in mapping.items() for d in digests}
    images = {}
    result = {}
    for i, group in enumerate(groups):
        for number, *box in group["places"]:
            if number not in images:
                images[number] = [(pymupdf.Rect(info["bbox"]), info["digest"].hex()[:10])
                                  for info in doc[number].get_image_info(hashes=True)]
            rect = pymupdf.Rect(box)
            word = next((named[d] for r, d in images[number] if d in named and r.intersects(rect)), None)
            if word:
                result[i] = word
                break
    return result


def text_lines(page):
    """(bbox, baseline, font size) of every text line on the page."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            span = max(line["spans"], key=lambda s: len(s["text"]))
            lines.append((pymupdf.Rect(line["bbox"]), span["origin"][1], span["size"]))
    return lines


def annotate(pdf_path, placements, out_path):
    """Write each name invisibly at its place; placements: [(page, rect, name)]."""
    doc = pymupdf.open(pdf_path)
    by_page = {}
    for number, rect, word in placements:
        by_page.setdefault(number, []).append((pymupdf.Rect(rect), word))
    for number, items in by_page.items():
        page = doc[number]
        lines = text_lines(page)
        for box, word in items:
            label = f"[{word}]"
            # Sit on the baseline and in the font size of the text line around
            # the icon; otherwise text extraction reads the label as its own line.
            overlap = lambda line: min(box.y1, line[0].y1) - max(box.y0, line[0].y0)
            near = [line for line in lines if overlap(line) > 0 and abs(line[0].x0 - box.x0) < 400]
            if near:
                _, baseline, size = max(near, key=overlap)
            else:
                baseline, size = box.y1 - box.height * 0.2, box.height * 0.8
            # Squeeze it to the icon's width, so it does not run into the next word.
            width = pymupdf.get_text_length(label, fontsize=size)
            squeeze = pymupdf.Matrix(min(1, 0.95 * box.width / width), 1)
            point = pymupdf.Point(box.x0, baseline)
            page.insert_text(point, label, fontsize=size, render_mode=3, morph=(point, squeeze))
    doc.save(out_path, garbage=3, deflate=True)
    return len(placements)


if __name__ == "__main__":
    for group in find_symbols(sys.argv[1]):
        print(f"{group['count']:4d}x  {group['examples'][0]}")
