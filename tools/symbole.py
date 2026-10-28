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
import math
import sys

import numpy
import pymupdf

RENDER_DPI = 110      # for finding ink; enough for icons of 8 pt and more
GAP = 0.45            # gap (in word-box heights, which include ascenders and
                      # descenders, ~1.6x the font size) that may hold an icon; a space is ~0.15
SIDE = 2.2            # how far (in line heights) to look before/after a line
ROW = 8               # same, for a row of icons beside a line
TALL = 1.8            # highest icon (in line heights) inside a line
TALL_SIDE = 2.5       # beside a line: may stand for a two-line paragraph (7 Wonders Duel)
WIDE = 3.2            # widest icon (in its height or the line height, the larger) inside a line
WIDE_SIDE = 2.2       # beside a line; wider is a row of icons or a banner
INK = 70              # colour distance from the background that counts as ink


_rendered = {}


def rendered(page):
    """The whole page as pixels, rendered once: a page has hundreds of spots."""
    key = (id(page.parent), page.number)
    if key not in _rendered:
        _rendered.clear()
        pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB, alpha=False)
        _rendered[key] = numpy.frombuffer(pix.samples, dtype=numpy.uint8).reshape(pix.height, pix.width, 3)
    return _rendered[key]


def ink(page, rect, words=()):
    """Pixels drawn in rect, not counting text, or None.

    Returns (xs, ys, width, height, scale, origin): pixel positions, the size
    of the cut-out, points per pixel and the cut-out's top left in points.
    """
    rect = rect & page.rect
    if rect.is_empty or rect.width < 2 or rect.height < 2:
        return None
    scale = 72 / RENDER_DPI
    page_pixels = rendered(page)
    left, top = round((rect.x0 - page.rect.x0) / scale), round((rect.y0 - page.rect.y0) / scale)
    right, bottom = round((rect.x1 - page.rect.x0) / scale), round((rect.y1 - page.rect.y0) / scale)
    pixels = page_pixels[top:bottom, left:right].astype(numpy.int16)
    h, w = pixels.shape[:2]
    if w < 4 or h < 4:
        return None
    rect = pymupdf.Rect(page.rect.x0 + left * scale, page.rect.y0 + top * scale,
                        page.rect.x0 + right * scale, page.rect.y0 + bottom * scale)
    # Text in the spot (neighbouring lines, the words beside a gap) is no icon.
    in_text = numpy.zeros((h, w), dtype=bool)
    for r in (pymupdf.Rect(wd[:4]) for wd in words):
        if r.intersects(rect):
            a, b = math.ceil((r.x0 - rect.x0) / scale), math.ceil((r.y0 - rect.y0) / scale)
            c, d = math.floor((r.x1 - rect.x0) / scale), math.floor((r.y1 - rect.y0) / scale)
            in_text[max(b, 0):max(d + 1, 0), max(a, 0):max(c + 1, 0)] = True
    edge = numpy.zeros((h, w), dtype=bool)
    edge[[0, -1], :] = edge[:, [0, -1]] = True
    border = pixels[edge & ~in_text]
    if not len(border):
        return None
    # Median per channel: robust against textured paper and bits of drawings.
    bg = numpy.sort(border, axis=0)[len(border) // 2]
    drawn = (numpy.abs(pixels - bg) > INK).any(axis=2) & ~in_text
    ys, xs = numpy.nonzero(drawn)
    if len(xs) < max(6, 0.03 * w * h):
        return None
    return xs.tolist(), ys.tolist(), w, h, scale, rect.tl


def ink_box(page, rect, words=(), open_sides=""):
    """Bounding box of what is drawn in rect, not counting text, or None.

    Also None if the drawing touches an edge of rect: then it is part of
    something bigger (a frame, a picture, the next column). Edges listed in
    open_sides ("l", "r", "t", "b") may be touched: a gap between two words
    is often a little narrower than the icon in it, and icons may fill a
    table cell.
    """
    found = ink(page, rect, words)
    if found is None:
        return None
    xs, ys, w, h, scale, origin = found
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (y0 == 0 and "t" not in open_sides) or (y1 == h - 1 and "b" not in open_sides) \
            or (x0 == 0 and "l" not in open_sides) or (x1 == w - 1 and "r" not in open_sides):
        return None
    return pymupdf.Rect(origin.x + x0 * scale, origin.y + y0 * scale,
                        origin.x + (x1 + 1) * scale, origin.y + (y1 + 1) * scale)


def split_row(page, box, words, h, from_right, tall, wide, in_cell=False):
    """The single icons of a row ("Holz / Lehm  Dieses Gebäude …", 7 Wonders Duel).

    The row is cut at empty columns. A thin piece as high as the row is a
    separator ("/"): it keeps the row going but is no icon. A thin, lower
    piece right next to another (a number badge on a card) belongs to it.
    Starting next to the text, pieces count as long as they follow each
    other closely; what comes after a wide gap belongs to something else.
    """
    # In a table cell the cell's lines are close: stay inside the icons.
    area = box if in_cell else box + (-0.3 * h, -0.3 * h, 0.3 * h, 0.3 * h)
    found = ink(page, area, words)
    if found is None:
        return []
    xs, ys, _, _, scale, origin = found
    columns, counts = {}, {}
    for x, y in zip(xs, ys):
        low, high = columns.get(x, (y, y))
        columns[x] = (min(low, y), max(high, y))
        counts[x] = counts.get(x, 0) + 1
    if in_cell:
        # Icons in a cell may touch each other: a column with only a little
        # ink (where two outlines meet) counts as empty.
        faint = 0.12 * (max(ys) - min(ys) + 1)
        columns = {x: c for x, c in columns.items() if counts[x] > faint}
    runs = []  # [x0, x1, y0, y1] in pixels
    for x in sorted(columns):
        low, high = columns[x]
        if runs and x - runs[-1][1] <= 1:
            run = runs[-1]
            run[1], run[2], run[3] = x, min(run[2], low), max(run[3], high)
        else:
            runs.append([x, x, low, high])
    row_height = max(ys) - min(ys) + 1
    # In a cell h is the row height, often well above the icons' width.
    narrowest = (0.4 if in_cell else 0.7) * h
    thin = lambda run: (run[1] - run[0] + 1) * scale < narrowest
    separator = lambda run: thin(run) and run[3] - run[2] + 1 >= 0.5 * row_height
    merged = []
    for run in runs:
        if merged and not separator(run) and not separator(merged[-1]) and run[0] - merged[-1][1] <= 4 \
                and (thin(run) or thin(merged[-1])):
            last = merged[-1]
            last[1], last[2], last[3] = run[1], min(last[2], run[2]), max(last[3], run[3])
        else:
            merged.append(run)
    pieces = [(origin.x + r[0] * scale, origin.x + (r[1] + 1) * scale, separator(r)) for r in merged]
    if from_right:
        pieces.reverse()
    icons, edge = [], box.x1 if from_right else box.x0
    for x0, x1, is_separator in pieces:
        if (edge - x1 if from_right else x0 - edge) > 1.2 * h:
            break
        edge = x0 if from_right else x1
        if is_separator:
            continue
        icon = ink_box(page, pymupdf.Rect(x0 - 0.5, area.y0, x1 + 0.5, area.y1), words, "lrtb" if in_cell else "lr")
        if icon and icon.width >= narrowest and 0.3 * h <= icon.height <= tall * h \
                and icon.width <= wide * max(h, icon.height):
            icons.append(icon)
    return icons


def candidates(page):
    """(spot, line height, words left, words right, in a table, open sides) where an icon may sit."""
    words = page.get_text("words")
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    spots, later = [], []

    def free(rect):
        # 1 pt slack: italic words reach a little left of their line.
        inner = rect + (1, 1, -1, -1)
        return not any(pymupdf.Rect(w[:4]).intersects(inner) for w in words)

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
        # A wide spot first for rows of icons, up to the next word (the other
        # column); if something bigger reaches into it, the narrow one may
        # still hold a single icon. Beside the first line of a paragraph an
        # icon may stand for the whole paragraph and reach down into the next
        # line; tried last, as the spot may then also catch the icon of the
        # next line.
        x0, x1 = line[0][0], line[-1][2]
        for below, into in ((pad, spots), ((TALL_SIDE - 1) * h, later)):
            y0, y1 = top - pad, bottom + below
            beside = [w for w in words if w[3] > y0 + 1 and w[1] < y1 - 1]
            left = max([x0 - ROW * h] + [w[2] + 1 for w in beside if w[2] < x0 - 1])
            right = min([x1 + ROW * h] + [w[0] - 1 for w in beside if w[0] > x1 + 1])
            for reach in dict.fromkeys((left, max(left, x0 - SIDE * h))):
                before = pymupdf.Rect(reach, y0, x0 - 0.05 * h, y1)
                if free(before):
                    into.append((before, h, [], texts, False, "r"))
            for reach in dict.fromkeys((right, min(right, x1 + SIDE * h))):
                after = pymupdf.Rect(x1 + 0.05 * h, y0, reach, y1)
                if free(after):
                    into.append((after, h, texts, [], False, "l"))
    spots += later
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
                    spots.append((inner, inner.height, row_text, [], True, "lrtb"))
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


def overlap(a, b):
    """Found twice: the boxes cover each other, not just touch (icons in a row may)."""
    return (a & b).get_area() > 0.2 * min(a.get_area(), b.get_area())


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
        # Beside a line several spots are tried (wide, narrow, reaching
        # down); once one holds icons, the others of that side are skipped.
        done = set()
        for spot, h, left, right, in_table, open_sides in candidates(page):
            side = (open_sides, round(spot.y0, 1), round(spot.x1 if open_sides == "r" else spot.x0, 1))
            if side in done:
                continue
            box = ink_box(page, spot, words, open_sides)
            if box is None:
                continue
            # Icon sized: about as high as the text (up to a little taller);
            # a table cell may hold several icons side by side.
            tall, wide = (TALL, WIDE) if open_sides == "lr" else (TALL_SIDE, WIDE_SIDE)
            if in_table:
                # Several icons side by side in a cell (Cena: the crests in use).
                if box.height < 6:
                    boxes = []
                elif box.width > 1.6 * box.height:
                    boxes = split_row(page, box, words, box.height, False, 1.2, 1.6, in_cell=True)
                else:
                    boxes = [box]
            elif box.width < 1.5 or (open_sides != "lr" and box.width < 0.5 * h):
                boxes = []  # a sliver of something reaching into the spot
            elif 0.3 * h <= box.height <= tall * h and box.width <= wide * max(h, box.height):
                boxes = [box]
            elif box.height <= tall * h:
                # Too wide for one icon: maybe a row of them. Text is to the
                # right of a spot before the line ("r"), else to the left.
                boxes = split_row(page, box, words, h, open_sides == "r", tall, wide)
            else:
                boxes = []
            for box in boxes:
                if any(overlap(box, other) for other in seen):
                    continue
                # A word inside: a frame or banner around text, no icon.
                if not in_table and any(box.contains(pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
                                        for w in words):
                    continue
                # Taller than an icon inside a line: only with some space to
                # the text; a shape flush with it is a banner behind the text.
                gap = spot.x1 - box.x1 if open_sides == "r" else box.x0 - spot.x0
                if open_sides in ("l", "r") and box.height > TALL * h and gap < 0.15 * h:
                    continue
                seen.append(box)
                found.append((None, fingerprint(page, box), page.number, box, example_text(left, right)))
                if open_sides in ("l", "r"):
                    done.add(side)

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
