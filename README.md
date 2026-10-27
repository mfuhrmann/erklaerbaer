# 🐻 Erklärbär

Lokaler KI-Regelerklärer für Brettspiele. Spieler wählen ein Spiel, stellen
ihre Regelfrage per Sprache oder Text und bekommen eine kurze Antwort mit
wörtlichem Zitat und Link auf die passende Seite im Regelheft.

Läuft komplett offline auf einem Laptop – gedacht für Spieleevents.

## Schnellstart

```bash
cp .env.example .env                       # einmalig; UID/GID anpassen (id -u, id -g)
docker compose up -d                       # Erklärbär auf http://localhost:8090
docker compose --profile werkzeuge up -d   # zusätzlich Open WebUI zum Testen
docker compose --profile werkzeuge down    # alles stoppen
docker compose logs -f erklaerbaer         # Logs ansehen
```

Gebraucht werden Docker mit Zugriff auf die GPU (`/dev/dri`, Vulkan) und grob
12–16 GB freier RAM (geschätzt; gemessen auf einem Laptop mit iGPU: ~20 GB
belegt inklusive Desktop, alle ~90 Regelhefte vorgewärmt). Beim ersten Start werden die Modelle geladen (~6,6 GB LLM,
~0,6 GB Whisper). Danach liest der Erklärbär die Regelhefte einmal ein
(„vorgewärmt“ im Log), damit auch die ersten Fragen der Gäste schnell
beantwortet werden. Regelhefte bringt jeder selbst mit (siehe unten) – im
Repository sind keine.

## Neues Spiel hinzufügen

**Am einfachsten über die Webseite:** unten „➕ Anleitung importieren“, Namen
eintippen, PDF wählen (geht auch vom Handy). Die App erkennt, ob das PDF Text
enthält (→ Docling) oder nur Bilder (→ Texterkennung) und nimmt das Spiel ohne
Neustart auf. Dauer: Sekunden bis wenige Minuten. Kein Passwortschutz –
jeder im WLAN kann importieren.

**Symbole:** Stehen im Regeltext Bildsymbole mitten im Satz (z. B. ein
Blutstropfen für „Blut“), hält der Import an und zeigt eine Galerie
(`/symbole?spiel=<id>`, auch später über „🔣 Symbole“ im Spiel erreichbar).
Dort bekommt jedes Symbol einmal seinen Begriff; er wird unsichtbar ins PDF
geschrieben (`tools/symbole.py`), damit die Sätze verständlich bleiben. Das
Original bleibt als `<id>.orig.pdf`, die Namen in `<id>.symbole.json`.
Automatisch benennen ging nicht zuverlässig (Text-LLM 3/35, gemma3:4b 0/4).

Von Hand:

1. PDF nach `regelwerke/<spiel-id>.pdf` legen, z. B. `regelwerke/flip-7.pdf`.
2. Umwandeln:
   ```bash
   tools/neues-spiel.sh regelwerke/flip-7.pdf     # PDF mit Text (Docling)
   tools/ocr-spiel.sh regelwerke/flip-7.pdf deu   # Scan / Schrift als Grafik
   ```
   `ocr-spiel.sh` nimmt `deu`, `eng` oder `deu+eng`, `negativ` als drittes
   Argument für helle Schrift auf dunklem Grund. Warnungen von
   `neues-spiel.sh` wie `Seite 4 nur zu 31% erkannt` bedeuten: Docling hat die
   Seite nicht gelesen, ihr Rohtext wurde angehängt.
3. Anzeigenamen in `regelwerke/spiele.json` eintragen.
4. `docker compose restart erklaerbaer`

Antworten testen ohne Browser:

```bash
python3 tools/ask.py regelwerke/flip-7.md "Wie gewinnt man?" "Was passiert bei Gleichstand?"
```

## Wie es funktioniert

```
Handy/Browser ──► erklaerbaer (FastAPI, :8090)
                    ├─ Sprache ──► whisper (whisper.cpp, Vulkan)
                    └─ Frage + ganzes Regelheft ──► ollama (Gemma 4 e4b, Vulkan)
```

- **Kein RAG:** Pro Frage kommt das komplette Regelheft des gewählten Spiels in
  den Kontext (typisch 4–8k Tokens, die größten ~30k). Regelfragen hängen oft an mehreren
  verstreuten Stellen, die eine Suche verfehlen würde.
- **Cache:** Ollama hält eingelesene Regelhefte im Speicher (mit Gemma 4 e4b
  ~11 KB pro Token, ein typisches Heft mit 5k Tokens ≈ 55 MB). Das Einlesen
  ist der teure Teil (~245 Tokens/s, ein großes Heft mit 20k Tokens ~80 s);
  liegt ein Heft im Cache, kommt die Antwort in ~2 s.
- **Vorwärmen:** Beim Start liest die App die größten Regelhefte ein, die in
  den Cache passen (mit Gemma 4 e4b passen ~90 Hefte locker hinein); neu
  importierte Spiele werden direkt nach dem Import eingelesen. Den Fortschritt
  zeigt die Startseite („⏳ Regelhefte werden vorbereitet: 29 von 92“), am Ende
  steht „vorwärmen fertig“ im Log. Fragen von
  Gästen unterbrechen das Vorwärmen (Ollama bearbeitet nur eine Anfrage
  gleichzeitig). Ist eine Weile niemand aktiv, frischt die App die
  vorgewärmten Hefte auf, damit verdrängte wieder im Cache sind.
- **Einstellungen** (Umgebungsvariablen, z. B. in `.env` neben `compose.yaml`):

  | Variable | Standard | Bedeutung |
  |---|---|---|
  | `CACHE_RAM_MIB` | 12288 | Prompt-Cache von llama-server in MiB; mehr RAM → mehr Spiele vorgewärmt |
  | `VORWAERMEN` | `gross` | `gross`, `alle`, `keine` oder `liste` (`regelwerke/vorwaermen.txt`, eine Spiel-ID pro Zeile) |
  | `VORWAERMEN_PAUSE` | 300 | Sekunden ohne Fragen, bis vorgewärmte Hefte aufgefrischt werden |
  | `ERKLAERBAER_MODELL` | gemma4:e4b | Sprachmodell (Alternative: qwen3:30b-a3b-instruct-2507-q4_K_M) |
  | `CACHE_KB_PRO_TOKEN` | 11 | Cache pro Token des Modells (gemma4:e4b 11, qwen3 52) |
  | `KV_CACHE_TYPE` | q8_0 | Genauigkeit des Caches; q4_0 halbiert ihn, liest ~30 % langsamer ein |
  | `KONTEXT_TOKENS` | 40960 | Kontextfenster; muss größtes Regelheft (Star Trek ~31k Tokens) + Verlauf + Antwort fassen |
- **Modell:** `gemma4:e4b` (Standard). Im Vergleich mit 28 Regelfragen aus 12
  Heften 55/56 richtig gegenüber 56/56 für `qwen3:30b-a3b-instruct-2507-q4_K_M`,
  aber doppelt so schnell (Einlesen ~245 statt ~123 Tokens/s, Antwort aus dem
  Cache ~2 statt ~4 s) bei einem Viertel des Speichers und einem Fünftel des
  Caches pro Token. Wechsel per `ERKLAERBAER_MODELL` und `CACHE_KB_PRO_TOKEN`
  in `.env`. Gemmas „Denken“ schaltet die App ab (sie fragt Ollama, ob das
  Modell denken kann).
- **Seitenansicht:** Der Link unter einer Antwort öffnet die Regelheft-Seite als
  Bild mit gelb markiertem Zitat (`/seite`) – funktioniert auch auf Handys ohne
  PDF-Betrachter.
- **Whisper** bekommt pro Spiel ein Vokabular aus dem Regelheft (Überschriften,
  Namen), damit es Begriffe wie „Marshal“ richtig erkennt.
- **Prompt** (`tools/ask.py`): nur aus dem Regelheft antworten, umgangssprachliche
  Begriffe zuordnen, wörtlich zitieren, prüfen ob das Zitat die Antwort belegt.

## Dateien

| Pfad | Inhalt |
|---|---|
| `app/server.py` | Backend: Spiele, Spracherkennung, Antworten, Import, Symbole, Seitenansicht, Vorwärmen |
| `app/static/index.html` | Oberfläche: Spielliste, Fragen mit Verlauf, Import |
| `app/static/seite.html` | Regelheft-Seite als Bild mit markiertem Zitat |
| `app/static/symbole.html` | Galerie zum Benennen von Bildsymbolen |
| `tools/neues-spiel.sh` | PDF mit Text → bereinigtes Markdown (Docling) |
| `tools/ocr-spiel.sh`, `tools/ocr_md.py` | Scans / Schrift als Grafik → Markdown (tesseract) |
| `tools/symbole.py` | Bildsymbole im Text finden und als unsichtbaren Text ins PDF schreiben |
| `tools/clean_md.py` | Bereinigung (wiederholte Überschriften, Bild-Platzhalter) |
| `tools/check_coverage.py` | findet Seiten (und Symbolnamen), die Docling verloren hat |
| `tools/ask.py` | System-Prompt, Modellwahl und Kommandozeilen-Test |
| `tools/symbol-experimente/` | Messskripte: Symbolerkennung, Modell- und Cache-Vergleich |
| `regelwerke/` | Regelhefte (nicht im Repository), siehe `regelwerke/README.md` |
| `sammlung/`, `bgg-sammlung.csv` | Spielesammlung (BGG-Export) und Liste noch fehlender Anleitungen |
| `logs/fragen.jsonl` | alle gestellten Fragen mit Antwort und Dauer |
| `models/` | Whisper-Modell |

Spiele direkt verlinken (z. B. für QR-Codes in der Schachtel):
`http://<laptop>:8090/?spiel=colt-express`

## Dienste und Ports

| Dienst | Port | Zweck |
|---|---|---|
| erklaerbaer | 8090 (LAN) | Oberfläche für Gäste |
| ollama | 127.0.0.1:11434 | LLM |
| whisper | – (nur intern) | Spracherkennung |
| open-webui | 127.0.0.1:3080 | Testen, Admin (Profil `werkzeuge`) |
| docling | 127.0.0.1:5001 | PDF-Umwandlung (Import, `neues-spiel.sh`), ~1,7 GB RAM |

Die Ollama-Modelle liegen in `/var/lib/ollama` (Pfad über `OLLAMA_DATA`
änderbar). Läuft auf dem Rechner zusätzlich ein natives Ollama, kollidiert es
auf Port 11434 – eines von beiden abschalten.

## Bekannte Grenzen

- **Kein HTTPS:** Browser geben das Mikrofon nur über HTTPS oder auf
  `localhost` frei. Handys im WLAN können bisher nur tippen.
- **Sonderregeln:** Das Modell hält Fähigkeiten einzelner Charaktere manchmal
  für allgemeine Regeln. Das Zitat in der Antwort macht das sichtbar; fehlt
  der Seitenlink darunter, ist das Zitat vermutlich frei formuliert.
- **Bilder:** Symbole im Fließtext werden über die Symbol-Galerie benannt;
  Symbolreihen am Zeilenende und Symbole in Tabellen ohne Linien erkennt sie
  noch nicht zuverlässig. Regeln, die nur in Abbildungen stehen, fehlen.
- **Seitenzahlen** sind PDF-Seiten, nicht unbedingt die aufgedruckten.
- **Gleichzeitige Fragen** werden nacheinander beantwortet; bei mehreren
  Tischen gleichzeitig wartet die letzte Frage auf die vorigen (je ~2 s).
- **Modell:** Gemma 4 e4b unterscheidet ähnliche Regelstellen etwas weniger
  sorgfältig als das größere Qwen3 30B (z. B. Ende eines Durchgangs vs. Ende
  des Spiels); wer den RAM hat, kann per `.env` wechseln.

## Lizenz

GPL-3.0, siehe [LICENSE](LICENSE). Regelhefte gehören nicht zum Projekt und
sind nicht im Repository – sie unterliegen dem Urheberrecht ihrer Verlage.
