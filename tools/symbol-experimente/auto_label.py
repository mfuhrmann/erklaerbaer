# auto_label.py <pdf> <out.json> [manual.json] : let the LLM name inline icons from their text context
import json, re, sys, time
import httpx
import pymupdf

MODEL = "qwen3:30b-a3b-instruct-2507-q4_K_M"
doc = pymupdf.open(sys.argv[1])

icons = {}  # digest -> contexts
for page in doc:
    words = page.get_text("words")
    for info in page.get_image_info(hashes=True):
        x0, y0, x1, y1 = info["bbox"]
        if (y1 - y0) > 30 or (x1 - x0) > 45 or (y1 - y0) < 4:
            continue
        mid = (y0 + y1) / 2
        line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - mid) < 4), key=lambda w: w[0])
        before = [w[4] for w in line if w[2] <= x0 + 1 and x0 - w[2] < 60]
        after = [w[4] for w in line if w[0] >= x1 - 1 and w[0] - x1 < 60]
        # Inside a sentence: text close by on the left and on the right.
        if not (before and after):
            continue
        key = info["digest"].hex()[:10]
        ctx = " ".join(w[4] for w in line if w[2] <= x0 + 1)[-70:] + " [■] " + " ".join(w[4] for w in line if w[0] >= x1 - 1)[:70]
        icons.setdefault(key, [])
        if ctx not in icons[key] and len(icons[key]) < 4:
            icons[key].append(ctx)

lines = [f"{k}: " + " || ".join(c) for k, c in icons.items()]
prompt = (
    "In einer Brettspiel-Anleitung stehen im Fließtext kleine Bildsymbole. Beim Umwandeln in Text gingen sie "
    "verloren; ihre Stelle ist mit [■] markiert. Unten steht pro Symbol (ID) der Text rund um die Stelle(n).\n"
    "Gib für jedes Symbol den Begriff an, für den es steht (ein Wort oder kurzer Begriff, wie er in der "
    "Anleitung verwendet wird, z. B. „Stärke“). Wenn der Text keinen klaren Hinweis gibt, antworte mit \"?\".\n"
    "Antworte nur mit JSON: {\"ID\": \"Begriff\", ...}\n\n" + "\n".join(lines))
started = time.time()
r = httpx.post("http://localhost:11434/api/chat", timeout=900, json={
    "model": MODEL, "stream": False, "format": "json", "keep_alive": -1,
    "options": {"temperature": 0, "num_predict": 4000},
    "messages": [{"role": "user", "content": prompt}]}).json()
labels = json.loads(r["message"]["content"])
print(f"{len(icons)} Symbole im Satz, {r.get('prompt_eval_count')} Tokens, {time.time() - started:.0f} s")
mapping = {}
for k, v in labels.items():
    if v and v != "?":
        mapping.setdefault(v, []).append(k)
json.dump(mapping, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print("Vorschläge:", {w: len(d) for w, d in mapping.items()})

if len(sys.argv) > 3:
    manual = {d: w for w, ds in json.load(open(sys.argv[3])).items() for d in ds}
    both = [k for k in icons if k in manual]
    right = [k for k in both if labels.get(k, "?").lower() == manual[k].lower()]
    unsure = [k for k in both if labels.get(k, "?") == "?"]
    wrong = [(manual[k], labels.get(k)) for k in both if k not in right and k not in unsure]
    print(f"Vergleich mit Hand-Zuordnung ({len(both)} Symbole): {len(right)} richtig, {len(unsure)} '?', {len(wrong)} falsch")
    print("falsch:", wrong)
    extra = [(k, labels[k]) for k in icons if k not in manual and labels.get(k, "?") != "?"]
    print("zusätzlich benannt (von Hand nicht zugeordnet):", extra[:20])
