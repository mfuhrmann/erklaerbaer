"""Erklärbär: answers board game rule questions by voice or text.

Run: uv run uvicorn app.server:app --host 0.0.0.0 --port 8090
"""
import asyncio
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.ask import MODEL, SYSTEM_PROMPT  # noqa: E402
from tools.check_coverage import page_count, page_text, words  # noqa: E402
from tools import symbole  # noqa: E402

RULES_DIR = ROOT / "regelwerke"
LOG_FILE = ROOT / "logs" / "fragen.jsonl"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
WHISPER_URL = os.environ.get("WHISPER_URL", "http://127.0.0.1:8081")

# Same sampling as tools/ask.py; the token limit stops runaway answers.
OPTIONS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "num_predict": 1024}

# Prompt cache of llama-server, same value as LLAMA_ARG_CACHE_RAM in compose.yaml.
CACHE_RAM_MIB = int(os.environ.get("CACHE_RAM_MIB", "8192"))
# Measured with q8_0 KV cache: 12288 MiB hold ~246,000 tokens.
CACHE_BYTES_PER_TOKEN = 52_000
# "gross": largest rulebooks that fit the cache, "alle", "keine",
# or "liste": the game ids in regelwerke/vorwaermen.txt (one per line).
WARM_MODE = os.environ.get("VORWAERMEN", "gross")
# Idle guests for this long: touch the warm rulebooks again, so ones pushed
# out of the cache by other games are read in before someone asks.
REFRESH_SECONDS = int(os.environ.get("VORWAERMEN_PAUSE", "300"))


def vocabulary(name, rules, limit=60):
    """Terms of a game that whisper should recognise, e.g. "Marshal".

    Whisper takes them as initial prompt and then prefers these spellings
    over similar sounding words ("Marschhahn").
    """
    # Short terms only; whole sentences from headings don't help whisper.
    headings = [h.strip(" :,.!?") for h in re.findall(r"^#+ (.+)$", rules, re.MULTILINE)]
    quoted = re.findall(r'"([^"\n]{3,30})"', rules)
    capitalised = Counter(re.findall(r"\b[A-ZÄÖÜ][a-zäöüß]{3,}\b", rules))
    terms = [name] + headings + quoted + [w for w, n in capitalised.most_common() if n >= 3]
    terms = [t for t in terms if 0 < len(t.split()) <= 3 and not t[0].isdigit()]
    unique = list(dict.fromkeys(t.title() if t.isupper() else t for t in terms))
    return ", ".join(unique[:limit])


ENGLISH = re.compile(r"\b(?:the|and|you|player)\b", re.IGNORECASE)
GERMAN = re.compile(r"\b(?:der|die|und|du|spieler)\b", re.IGNORECASE)


def game_names():
    names = RULES_DIR / "spiele.json"
    return json.loads(names.read_text(encoding="utf-8")) if names.exists() else {}


def load_game(path, names):
    game_id = path.stem
    name = names.get(game_id, game_id.replace("-", " ").title())
    rules = path.read_text(encoding="utf-8")
    pdf = path.with_suffix(".pdf")
    return {
        "id": game_id,
        "name": name,
        "rules": rules,
        "vocabulary": vocabulary(name, rules),
        # Shown to guests, since answers then quote an English rulebook.
        "lang": "en" if len(ENGLISH.findall(rules)) > len(GERMAN.findall(rules)) else "de",
        # Prompt size estimate: measured 3.35 characters per token for German,
        # 4.03 for English; the mean is off by about 9% either way.
        "tokens": int(len(SYSTEM_PROMPT.format(rules=rules)) / 3.7),
        "pdf": pdf if pdf.exists() else None,
        # Word runs of every PDF page, to find the page a quote is from.
        "pages": [words(page_text(str(pdf), p)) for p in range(1, page_count(str(pdf)) + 1)]
        if pdf.exists() else [],
    }


def load_games():
    """Every cleaned rulebook (*.md, not *.docling.md) is one game."""
    names = game_names()
    return {
        path.stem: load_game(path, names)
        for path in sorted(RULES_DIR.glob("*.md"))
        if not path.name.endswith(".docling.md")
    }


GAMES = load_games()
app = FastAPI(title="Erklärbär")


def chat_payload(game, question, stream, options=OPTIONS, history=()):
    # Earlier questions come after the rulebook, so Ollama's cached
    # rulebook prefix stays valid for follow-up questions.
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(rules=game["rules"])}]
    for turn in history:
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer})
    messages.append({"role": "user", "content": question})
    return {
        "model": MODEL,
        "stream": stream,
        "keep_alive": -1,
        "options": options,
        "messages": messages,
    }


def games_to_warm():
    """Rulebooks to keep in Ollama's cache, largest first.

    Reading a rulebook costs more than linear in its size (Abomination:
    21,000 tokens, 166 s; Quoridor: 1,000 tokens, 3 s), so the big ones are
    worth keeping and the small ones can be read when someone asks.
    """
    by_size = sorted(GAMES.values(), key=lambda g: g["tokens"], reverse=True)
    if WARM_MODE == "keine":
        return []
    if WARM_MODE == "alle":
        return by_size
    if WARM_MODE == "liste":
        ids = (RULES_DIR / "vorwaermen.txt").read_text(encoding="utf-8").split()
        return [g for g in by_size if g["id"] in ids]
    # Leave 10% of the cache for the questions themselves and unwarmed games.
    budget = CACHE_RAM_MIB * 1024 * 1024 * 0.9 / CACHE_BYTES_PER_TOKEN
    chosen, used = [], 0
    for game in by_size:
        if used + game["tokens"] <= budget:
            chosen.append(game)
            used += game["tokens"]
    return chosen


# Ollama works on one request at a time, so a guest's question would wait
# for a rulebook being warmed up. Questions therefore interrupt warming.
active_questions = 0
question_arrived = asyncio.Event()
last_question = 0.0


async def warm(client, game):
    """Read one rulebook into Ollama's cache, giving way to questions."""
    payload = chat_payload(game, "Hallo", stream=False, options={**OPTIONS, "num_predict": 1})
    while True:
        while active_questions:
            await asyncio.sleep(1)
        question_arrived.clear()
        request = asyncio.create_task(client.post(f"{OLLAMA_URL}/api/chat", json=payload))
        interrupt = asyncio.create_task(question_arrived.wait())
        done, _ = await asyncio.wait({request, interrupt}, return_when=asyncio.FIRST_COMPLETED)
        interrupt.cancel()
        if request in done:
            request.result().raise_for_status()
            return
        # Closing the connection makes Ollama stop after its current batch.
        request.cancel()
        print(f"vorwärmen unterbrochen: {game['name']}", flush=True)


@app.on_event("startup")
async def warm_up():
    """Keep the chosen rulebooks in Ollama's cache before guests ask."""
    chosen = games_to_warm()
    print(f"vorwärmen ({WARM_MODE}): {len(chosen)} von {len(GAMES)} Spielen, "
          f"~{sum(g['tokens'] for g in chosen)} Tokens, Cache {CACHE_RAM_MIB} MiB", flush=True)

    async def run():
        async with httpx.AsyncClient(timeout=600) as client:
            for game in chosen:
                started = time.time()
                await warm(client, game)
                print(f"vorgewärmt: {game['name']} ({time.time() - started:.0f} s)", flush=True)
            # Touching a rulebook that is still cached takes about a second.
            while chosen:
                await asyncio.sleep(REFRESH_SECONDS)
                if time.time() - last_question < REFRESH_SECONDS:
                    continue
                for game in chosen:
                    await warm(client, game)

    asyncio.create_task(run())


@app.get("/api/games")
def games():
    return [{"id": g["id"], "name": g["name"], "pdf": g["pdf"] is not None, "lang": g["lang"],
             "seiten": len(g["pages"])}
            for g in GAMES.values()]


def get_game(game_id):
    game = GAMES.get(game_id)
    if game is None:
        raise HTTPException(404, "Unbekanntes Spiel")
    return game


@app.get("/api/games/{game_id}/pdf")
def rulebook_pdf(game_id: str):
    game = get_game(game_id)
    if game["pdf"] is None:
        raise HTTPException(404, "Kein PDF vorhanden")
    return FileResponse(game["pdf"], media_type="application/pdf")


# --- Page view: phones often can't show PDFs (or jump to a page), so pages are
# rendered as images and the quote is highlighted on them.

PAGE_CACHE = Path("/tmp/seiten")
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


def get_page_number(game, page):
    if game["pdf"] is None or not 1 <= page <= len(game["pages"]):
        raise HTTPException(404, "Seite nicht vorhanden")
    return page


@app.get("/api/games/{game_id}/seite/{page}.jpg")
def page_image(game_id: str, page: int):
    game = get_game(game_id)
    get_page_number(game, page)
    pdf = game["pdf"]
    # The modification time is part of the name, so a re-converted PDF gets new images.
    image = PAGE_CACHE / f"{game_id}-{int(pdf.stat().st_mtime)}-{page}.jpg"
    if not image.exists():
        PAGE_CACHE.mkdir(exist_ok=True)
        subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=80", "-r", "130", "-f", str(page),
                        "-l", str(page), "-singlefile", str(pdf), str(image.with_suffix(""))], check=True)
    return FileResponse(image, media_type="image/jpeg")


@app.get("/api/games/{game_id}/seite/{page}/markierung")
def quote_boxes(game_id: str, page: int, quote: str):
    """Boxes (fractions of the page size) around the words of the quote on this page."""
    game = get_game(game_id)
    get_page_number(game, page)
    layout = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox-layout", str(game["pdf"]), "-"],
                            capture_output=True, text=True, check=True).stdout
    size = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', layout)
    width, height = float(size.group(1)), float(size.group(2))
    page_words = [(tuple(map(float, m.groups()[:4])), html.unescape(m.group(5))) for m in WORD.finditer(layout)]
    # Same comparison as the page search: runs of three words.
    runs = words(quote)
    tokens = [(i, t) for i, (_, text) in enumerate(page_words) for t in re.findall(r"\w{2,}", text.lower())]
    hit = set()
    for j in range(len(tokens) - 2):
        if " ".join(t for _, t in tokens[j:j + 3]) in runs:
            hit.update(i for i, _ in tokens[j:j + 3])
    # One box per line: neighbouring hit words with about the same height.
    boxes = []
    for i in sorted(hit):
        x0, y0, x1, y1 = page_words[i][0]
        if boxes and abs(boxes[-1][1] - y0) < (y1 - y0) / 2 and x0 - boxes[-1][2] < 3 * (y1 - y0):
            boxes[-1] = [min(boxes[-1][0], x0), min(boxes[-1][1], y0), max(boxes[-1][2], x1), max(boxes[-1][3], y1)]
        else:
            boxes.append([x0, y0, x1, y1])
    return {"boxes": [[b[0] / width, b[1] / height, b[2] / width, b[3] / height] for b in boxes]}


@app.get("/seite")
def page_view():
    return FileResponse(ROOT / "app" / "static" / "seite.html")


@app.get("/symbole")
def symbol_gallery():
    return FileResponse(ROOT / "app" / "static" / "symbole.html")


@app.get("/api/games/{game_id}/page")
def quote_page(game_id: str, quote: str):
    """PDF page that contains most of the quote, or null if none fits."""
    quote_words = words(quote)
    best, best_hits = None, 0
    for number, page_words in enumerate(get_game(game_id)["pages"], start=1):
        hits = len(quote_words & page_words)
        if hits > best_hits:
            best, best_hits = number, hits
    # Require a real overlap, not just a few common phrases.
    if not quote_words or best_hits < max(2, len(quote_words) // 3):
        best = None
    return {"page": best}


# --- Import: drop a rulebook PDF in from any device (e.g. a phone at the table).

imports = {}  # job id -> {"status": ..., "game": ..., "message": ...}
import_lock = asyncio.Lock()  # one conversion at a time; docling and OCR are heavy


def slug(name):
    name = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def has_text_layer(pdf):
    """Scans and PDFs with fonts as outlines have (almost) no extractable text."""
    pages = page_count(str(pdf))
    return sum(len(page_text(str(pdf), p).split()) for p in range(1, pages + 1)) >= 20 * pages


async def convert(job, game_id, name, pdf, ocr=False, new=True):
    async with import_lock:
        imports[job]["status"] = "läuft"
        # OCR keeps German and English text; docling loses text on image PDFs.
        if ocr:
            # ocr-spiel.sh replaces the PDF with a rendered one; keep the upload.
            shutil.copy(pdf, RULES_DIR / f"{game_id}.orig.pdf")
            imports[job]["message"] = "Keine Textebene – Texterkennung läuft"
            command = ["bash", str(ROOT / "tools" / "ocr-spiel.sh"), str(pdf), "deu+eng"]
        else:
            command = ["bash", str(ROOT / "tools" / "neues-spiel.sh"), str(pdf)]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output = (await process.communicate())[0].decode(errors="replace").strip()
        if process.returncode != 0:
            if new:
                pdf.unlink(missing_ok=True)
            imports[job].update(status="fehler", message=output[-500:])
            return
        names = game_names()
        names[game_id] = name
        (RULES_DIR / "spiele.json").write_text(
            json.dumps(dict(sorted(names.items())), ensure_ascii=False, indent=2), encoding="utf-8")
        GAMES[game_id] = load_game(RULES_DIR / f"{game_id}.md", names)
        print(f"importiert: {name} ({output.splitlines()[-1]})", flush=True)
        imports[job].update(status="fertig", message=output.splitlines()[-1])


async def run_import(job, game_id, name, pdf):
    if not has_text_layer(pdf):
        await convert(job, game_id, name, pdf, ocr=True)
        return
    imports[job].update(status="läuft", message="Suche Symbole im Text")
    if await asyncio.to_thread(symbol_groups, game_id):
        # Wait for someone to name them in the gallery (/symbole).
        imports[job].update(status="symbole", message="Symbole benennen")
        return
    await convert(job, game_id, name, pdf)


# --- Symbols: icons inside sentences are named once per rulebook in a gallery
# and written into the PDF as invisible text (tools/symbole.py).

SYMBOL_DIR = RULES_DIR / ".symbole"


def original_pdf(game_id):
    """The PDF before symbol names were written in; kept as <id>.orig.pdf."""
    original = RULES_DIR / f"{game_id}.orig.pdf"
    if not original.exists():
        shutil.copy(RULES_DIR / f"{game_id}.pdf", original)
    return original


def symbol_groups(game_id):
    """Groups of similar icons, found once and kept with their images."""
    folder = SYMBOL_DIR / game_id
    index = folder / "gruppen.json"
    if index.exists():
        return json.loads(index.read_text(encoding="utf-8"))
    groups = symbole.find_symbols(str(original_pdf(game_id)))
    folder.mkdir(parents=True, exist_ok=True)
    for i, group in enumerate(groups):
        (folder / f"{i}.png").write_bytes(group.pop("png"))
    index.write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
    return groups


def pending_job(game_id):
    return next((job for job, state in imports.items()
                 if state["game"] == game_id and state["status"] == "symbole"), None)


def saved_names(game_id, groups):
    """Group index -> name from <id>.symbole.json.

    Format {"names": {"0": "Blut", ...}}; the older format {"Blut": [image
    digests]} (Gunsen, named by hand) is matched to the groups by position.
    """
    mapping_file = RULES_DIR / f"{game_id}.symbole.json"
    if not mapping_file.exists():
        return {}
    saved = json.loads(mapping_file.read_text(encoding="utf-8"))
    if "names" in saved:
        return {int(i): word for i, word in saved["names"].items()}
    return symbole.names_from_digests(str(original_pdf(game_id)), groups, saved)


@app.get("/api/symbole/{game_id}")
def symbols(game_id: str):
    job = pending_job(game_id)
    if game_id not in GAMES and job is None:
        raise HTTPException(404, "Unbekanntes Spiel")
    all_groups = symbol_groups(game_id)
    named = saved_names(game_id, all_groups)
    groups = [{
        "id": i, "count": group["count"], "examples": group["examples"],
        "name": named.get(i) or "",
        # Rare icons are mostly portraits and decorations.
        "ignore": i not in named and (bool(named) or group["count"] < 3),
    } for i, group in enumerate(all_groups)]
    name = GAMES[game_id]["name"] if game_id in GAMES else imports[job]["name"]
    return {"name": name, "job": job, "groups": groups}


@app.get("/api/symbole/{game_id}/{group}.png")
def symbol_image(game_id: str, group: int):
    image = SYMBOL_DIR / game_id / f"{group}.png"
    if not image.exists():
        raise HTTPException(404, "Kein Bild")
    return FileResponse(image, media_type="image/png")


class SymbolNames(BaseModel):
    # Group id -> name; "" marks it as "[Symbol]", null leaves it out. All null
    # skips naming (the rulebook is converted without symbol names).
    names: dict[int, str | None]


@app.post("/api/symbole/{game_id}")
async def name_symbols(game_id: str, body: SymbolNames):
    job = pending_job(game_id)
    if game_id not in GAMES and job is None:
        raise HTTPException(404, "Unbekanntes Spiel")
    groups = symbol_groups(game_id)
    names = {i: (word.strip().strip("[]") or "Symbol") for i, word in body.names.items() if word is not None}
    (RULES_DIR / f"{game_id}.symbole.json").write_text(
        json.dumps({"names": names}, ensure_ascii=False, indent=1), encoding="utf-8")
    placements = [(number, box, names[i]) for i, group in enumerate(groups) if i in names
                  for number, *box in group["places"]]
    pdf = RULES_DIR / f"{game_id}.pdf"
    await asyncio.to_thread(symbole.annotate, str(original_pdf(game_id)), placements, str(pdf))
    new = job is not None
    if job is None:
        job = uuid.uuid4().hex[:8]
        imports[job] = {"status": "wartet", "game": game_id, "message": "", "name": GAMES[game_id]["name"]}
    asyncio.create_task(convert(job, game_id, imports[job]["name"], pdf, new=new))
    return {"job": job}


@app.post("/api/import")
async def import_rulebook(pdf: UploadFile, name: str = Form(...)):
    name = name.strip()
    game_id = slug(name)
    if not game_id:
        raise HTTPException(400, "Bitte einen Spielnamen angeben.")
    path = RULES_DIR / f"{game_id}.pdf"
    if game_id in GAMES or path.exists():
        existing = GAMES[game_id]["name"] if game_id in GAMES else name
        raise HTTPException(409, f"„{existing}“ gibt es schon (oder wird gerade importiert).")
    data = await pdf.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Das ist keine PDF-Datei.")
    path.write_bytes(data)
    job = uuid.uuid4().hex[:8]
    imports[job] = {"status": "wartet", "game": game_id, "message": "", "name": name}
    asyncio.create_task(run_import(job, game_id, name, path))
    return {"job": job, "game": game_id}


@app.get("/api/import/{job}")
def import_status(job: str):
    if job not in imports:
        raise HTTPException(404, "Unbekannter Import")
    return imports[job]


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile, game: str = Form("")):
    data = {"response_format": "json"}
    if game in GAMES:
        data["prompt"] = GAMES[game]["vocabulary"]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{WHISPER_URL}/inference",
            files={"file": ("frage.wav", await audio.read(), "audio/wav")},
            data=data,
        )
    response.raise_for_status()
    return {"text": response.json()["text"].strip()}


class Turn(BaseModel):
    question: str
    answer: str


class Question(BaseModel):
    game: str
    question: str
    # Previous questions and answers, so follow-ups like
    # "Mit Sheriff meinte ich Marshal" make sense.
    history: list[Turn] = []


@app.post("/api/ask")
async def ask(q: Question):
    game = get_game(q.game)

    async def stream():
        global active_questions, last_question
        started = time.time()
        answer = []
        active_questions += 1
        question_arrived.set()
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                payload = chat_payload(game, q.question, stream=True, history=q.history[-2:])
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)["message"]["content"]
                        answer.append(chunk)
                        yield chunk
        finally:
            active_questions -= 1
            last_question = time.time()
        with LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(json.dumps({
                "zeit": time.strftime("%Y-%m-%d %H:%M:%S"),
                "spiel": game["id"],
                "frage": q.question,
                "antwort": "".join(answer),
                "sekunden": round(time.time() - started, 1),
            }, ensure_ascii=False) + "\n")

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
