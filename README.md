# 🐻 Erklärbär

Lokaler KI-Regelerklärer für Brettspiele. Spieler wählen ein Spiel, stellen
ihre Regelfrage per Sprache oder Text und bekommen eine kurze Antwort mit
wörtlichem Zitat und Link auf die passende Seite im Regelheft.

Läuft komplett offline auf einem Laptop – gedacht für Spieleevents.

## Schnellstart

```bash
cp .env.example .env                       # einmalig; UID/GID anpassen (id -u, id -g)
docker compose up -d                       # Erklärbär auf http://localhost:8090
                                           # und https://<laptop-ip>:8443 (Handys)
docker compose --profile werkzeuge up -d   # zusätzlich Open WebUI zum Testen
docker compose --profile werkzeuge down    # alles stoppen
docker compose logs -f erklaerbaer         # Logs ansehen
```

Gebraucht werden Docker mit Zugriff auf die GPU (`/dev/dri`, Vulkan) und
freier RAM für Modell (~7 GB), Whisper und App (~1 GB) plus den Cache der
Regelhefte (Standard 8 GB, `CACHE_RAM_MIB`). Gemessen auf einem Laptop mit
iGPU: ~20 GB belegt inklusive Desktop bei 8 GB Cache. Beim ersten Start werden
die Modelle geladen (~6,6 GB LLM, ~0,6 GB Whisper). Danach liest der Erklärbär die Regelhefte einmal ein
(„vorgewärmt“ im Log), damit auch die ersten Fragen der Gäste schnell
beantwortet werden. Regelhefte bringt jeder selbst mit (siehe unten) – im
Repository sind keine.

## Neues Spiel hinzufügen

**Am einfachsten über die Webseite:** unten „➕ Anleitung importieren“, Namen
eintippen, PDF wählen (geht auch vom Handy). Die App erkennt, ob das PDF Text
enthält (→ pymupdf4llm) oder nur Bilder (→ Texterkennung) und nimmt das Spiel ohne
Neustart auf. Dauer: Sekunden bis wenige Minuten. Kein Passwortschutz –
jeder im WLAN kann importieren.

**Symbole:** Stehen im Regeltext Bildsymbole mitten im Satz (z. B. ein
Blutstropfen für „Blut“), hält der Import an und zeigt eine Galerie
(`/symbole?spiel=<id>`, auch später über „🔣 Symbole“ im Spiel erreichbar).
Dort bekommt jedes Symbol einmal seinen Begriff (Links „Seite N“ zeigen die
Regelheft-Seite mit rot markiertem Symbol, z. B. neben seiner Legende); er wird unsichtbar ins PDF
geschrieben (`tools/symbole.py`), damit die Sätze verständlich bleiben. Das
Original bleibt als `<id>.orig.pdf`, die Namen in `<id>.symbole.json`.
Automatisch benennen ging nicht zuverlässig (Text-LLM 3/35, gemma3:4b 0/4).

Von Hand:

1. PDF nach `regelwerke/<spiel-id>.pdf` legen, z. B. `regelwerke/flip-7.pdf`.
2. Umwandeln:
   ```bash
   uv run bash tools/neues-spiel.sh regelwerke/flip-7.pdf   # PDF mit Text (pymupdf4llm)
   tools/ocr-spiel.sh regelwerke/flip-7.pdf deu              # Scan / Schrift als Grafik
   ```
   `ocr-spiel.sh` nimmt `deu`, `eng` oder `deu+eng`, `negativ` als drittes
   Argument für helle Schrift auf dunklem Grund. Warnungen von
   `neues-spiel.sh` wie `Seite 4 nur zu 31% erkannt` bedeuten: die Umwandlung
   hat die Seite nicht vollständig gelesen, ihr Rohtext wurde angehängt.
   Umgewandelt wird mit pymupdf4llm (statt früher Docling: im Vergleich mehr
   Text erhalten, Symbolnamen behalten, 2–3× schneller, kein eigener Dienst).
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
  den Kontext (typisch 2–7k Tokens, die größten ~30k). Regelfragen hängen oft an mehreren
  verstreuten Stellen, die eine Suche verfehlen würde.
- **Cache:** Ollama hält eingelesene Regelhefte im Speicher. Mit Gemma 4 e4b
  sind das ~9 KB pro Token plus 2–4 Sprungpunkte zu je bis zu ~10 MB: Gemma
  rechnet mit einem gleitenden Fenster, deshalb kann llama.cpp nur an diesen
  Punkten im Cache weitermachen. Im Schnitt über alle Hefte ~15 KB pro Token
  (92 Hefte, 567k Tokens ≈ 8,1 GB). Das Einlesen ist der teure Teil
  (~245 Tokens/s, ein großes Heft mit 20k Tokens ~80 s); liegt ein Heft im
  Cache, kommt die Antwort in ~2–4 s, je nach Länge.
- **Vorwärmen:** Beim Start liest die App die größten Regelhefte ein, die in
  90 % des Caches passen (geschätzt über `CACHE_KB_PRO_TOKEN`; bei 8 GB 62 von
  92 Heften, bei 12 GB alle; die kleinen liest Ollama bei der ersten Frage in
  wenigen Sekunden). Neu importierte Spiele werden direkt nach dem Import
  eingelesen. Vorgewärmt wird mit leerer Frage, damit der letzte Sprungpunkt
  vor dem Beginn jeder echten Frage liegt (sonst liest die erste Frage
  ~2000 Tokens neu, ~8 s). Den Fortschritt
  zeigt die Startseite („⏳ Regelhefte werden vorbereitet: 29 von 92“), am Ende
  steht „vorwärmen fertig“ im Log. Fragen von
  Gästen unterbrechen das Vorwärmen (Ollama bearbeitet nur eine Anfrage
  gleichzeitig). Ist eine Weile niemand aktiv, frischt die App die
  vorgewärmten Hefte auf, damit verdrängte wieder im Cache sind.
- **Einstellungen** (Umgebungsvariablen, z. B. in `.env` neben `compose.yaml`):

  | Variable | Standard | Bedeutung |
  |---|---|---|
  | `CACHE_RAM_MIB` | 8192 | Cache für gelesene Regelhefte in MiB. Alle ~90 brauchen mit gemma4:e4b ~8 GB (Text plus Sprungpunkte, die llama.cpp wegen Gemmas Gleitfenster speichert); jede Frage legt weitere an. Reserve lassen (z. B. 12288), sonst verdrängt der Cache ganze Hefte und das Auffrischen liest sie minutenlang neu |
  | `VORWAERMEN` | `gross` | `gross`, `alle`, `keine` oder `liste` (`regelwerke/vorwaermen.txt`, eine Spiel-ID pro Zeile) |
  | `VORWAERMEN_PAUSE` | 300 | Sekunden ohne Fragen, bis vorgewärmte Hefte aufgefrischt werden |
  | `ERKLAERBAER_MODELL` | gemma4:e4b | Sprachmodell (Alternative: qwen3:30b-a3b-instruct-2507-q4_K_M) |
  | `CACHE_KB_PRO_TOKEN` | 15 | Cache pro Token des Modells inklusive Sprungpunkte, Grundlage fürs Vorwärmen (gemma4:e4b ~15, qwen3 52) |
  | `KV_CACHE_TYPE` | q8_0 | Genauigkeit des Caches; q4_0 halbiert ihn, liest ~30 % langsamer ein |
  | `KONTEXT_TOKENS` | 40960 | Kontextfenster; muss größtes Regelheft (Star Trek ~31k Tokens) + Verlauf + Antwort fassen |
- **Modell:** `gemma4:e4b` (Standard). Im Vergleich mit 28 Regelfragen aus 12
  Heften 55/56 richtig (56/56 mit den pymupdf4llm-Texten) gegenüber 56/56 für
  `qwen3:30b-a3b-instruct-2507-q4_K_M`, aber doppelt so schnell (Einlesen ~245 statt ~123 Tokens/s, Antwort aus dem
  Cache ~2 statt ~4 s) bei einem Viertel des Speichers und weniger als einem
  Drittel des Caches pro Token. Wechsel per `ERKLAERBAER_MODELL` und `CACHE_KB_PRO_TOKEN`
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
| `tools/neues-spiel.sh`, `tools/pdf_md.py` | PDF mit Text → bereinigtes Markdown (pymupdf4llm) |
| `tools/ocr-spiel.sh`, `tools/ocr_md.py` | Scans / Schrift als Grafik → Markdown (tesseract) |
| `tools/symbole.py` | Bildsymbole im Text finden und als unsichtbaren Text ins PDF schreiben |
| `tools/clean_md.py` | Bereinigung (wiederholte Überschriften, Bild-Platzhalter) |
| `tools/check_coverage.py` | findet Seiten (und Symbolnamen), die bei der Umwandlung verloren gingen |
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
| https | 8443 (LAN) | dieselbe Oberfläche per HTTPS (Spracheingabe am Handy) |
| ollama | 127.0.0.1:11434 | LLM |
| whisper | – (nur intern) | Spracherkennung |
| open-webui | 127.0.0.1:3080 | Testen, Admin (Profil `werkzeuge`) |

Die Ollama-Modelle liegen in `/var/lib/ollama` (Pfad über `OLLAMA_DATA`
änderbar). Läuft auf dem Rechner zusätzlich ein natives Ollama, kollidiert es
auf Port 11434 – eines von beiden abschalten.

## Bekannte Grenzen

- **HTTPS nur selbst signiert:** Browser geben das Mikrofon nur über HTTPS
  frei. Caddy (`https/caddy.json`) liefert `https://<laptop>:8443` mit eigenem
  Zertifikat für jede IP; Gäste bestätigen einmal die Warnung. Über
  `http://…:8090` zeigt die Startseite einen Link dorthin. Das Zertifikat gilt
  30 Tage; nach der Erneuerung (etwa alle 20 Tage) kommt die Warnung einmal
  erneut.
- **Sonderregeln:** Das Modell hält Fähigkeiten einzelner Charaktere manchmal
  für allgemeine Regeln. Das Zitat in der Antwort macht das sichtbar; fehlt
  der Seitenlink darunter, ist das Zitat vermutlich frei formuliert.
- **Bilder:** Symbole im Fließtext und Symbolreihen neben einer Zeile
  („Holz / Lehm  Dieses Gebäude …“) und Symbole in Tabellenzellen werden
  über die Symbol-Galerie benannt. Regeln, die nur in Abbildungen stehen
  (z. B. Kartenübersichten), fehlen.
- **Seitenzahlen** sind PDF-Seiten, nicht unbedingt die aufgedruckten.
- **Gleichzeitige Fragen** werden nacheinander beantwortet; bei mehreren
  Tischen gleichzeitig wartet die letzte Frage auf die vorigen (je ~2–4 s).
- **Modell:** Gemma 4 e4b unterscheidet ähnliche Regelstellen etwas weniger
  sorgfältig als das größere Qwen3 30B (z. B. Ende eines Durchgangs vs. Ende
  des Spiels); wer den RAM hat, kann per `.env` wechseln.

## Lizenz

GPL-3.0, siehe [LICENSE](LICENSE). Regelhefte gehören nicht zum Projekt und
sind nicht im Repository – sie unterliegen dem Urheberrecht ihrer Verlage.
