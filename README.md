# 🐻 Erklärbär

Lokaler KI-Regelerklärer für Brettspiele. Spieler wählen ein Spiel, stellen
ihre Regelfrage per Sprache oder Text und bekommen eine kurze Antwort mit
wörtlichem Zitat und Link auf die passende Seite im Regelheft.

Läuft komplett offline auf einem Laptop – gedacht für Spieleevents.

## Schnellstart

```bash
docker compose up -d                       # Erklärbär auf http://localhost:8090
docker compose --profile werkzeuge up -d   # zusätzlich Open WebUI und Docling
docker compose --profile werkzeuge down    # alles stoppen
docker compose logs -f erklaerbaer         # Logs ansehen
```

Beim ersten Start werden die Modelle geladen (~18 GB LLM, ~0,6 GB Whisper).
Danach liest der Erklärbär jedes Regelheft einmal ein („vorgewärmt“ im Log),
damit die ersten Fragen der Gäste schnell beantwortet werden.

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
                    └─ Frage + ganzes Regelheft ──► ollama (Qwen3 30B, Vulkan)
```

- **Kein RAG:** Pro Frage kommt das komplette Regelheft des gewählten Spiels in
  den Kontext (typisch 4–8k Tokens). Regelfragen hängen oft an mehreren
  verstreuten Stellen, die eine Suche verfehlen würde.
- **Cache:** Ollama hält eingelesene Regelhefte im Speicher (~52 KB pro Token,
  ein typisches Heft 5k Tokens ≈ 250 MB). Einlesen kostet überproportional
  mit der Größe: Quoridor (1k Tokens) 3 s, Abomination (21k Tokens) 166 s;
  danach antwortet ein Spiel in 2–12 s.
- **Vorwärmen:** Beim Start liest die App die größten Regelhefte ein, die in
  den Cache passen; kleine liest Ollama bei Bedarf in Sekunden. Fragen von
  Gästen unterbrechen das Vorwärmen (Ollama bearbeitet nur eine Anfrage
  gleichzeitig). Ist eine Weile niemand aktiv, frischt die App die
  vorgewärmten Hefte auf, damit verdrängte wieder im Cache sind.
- **Einstellungen** (Umgebungsvariablen, z. B. in `.env` neben `compose.yaml`):

  | Variable | Standard | Bedeutung |
  |---|---|---|
  | `CACHE_RAM_MIB` | 12288 | Prompt-Cache von llama-server in MiB; mehr RAM → mehr Spiele vorgewärmt |
  | `VORWAERMEN` | `gross` | `gross`, `alle`, `keine` oder `liste` (`regelwerke/vorwaermen.txt`, eine Spiel-ID pro Zeile) |
  | `VORWAERMEN_PAUSE` | 300 | Sekunden ohne Fragen, bis vorgewärmte Hefte aufgefrischt werden |
  | `KONTEXT_TOKENS` | 40960 | Kontextfenster; muss größtes Regelheft (Star Trek ~31k Tokens) + Verlauf + Antwort fassen |
- **Modell:** `qwen3:30b-a3b-instruct-2507-q4_K_M`. MoE-Modell, rechnet pro
  Token nur ~3B Parameter, daher schnell auf der iGPU. Die Hybrid-Variante
  `qwen3:30b-a3b` ist ungeeignet: Sie denkt trotz `think: false` laut und
  läuft sich fest.
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
| `app/server.py` | Backend: Spiele, Spracherkennung, Antworten, PDF-Seitensuche |
| `app/static/index.html` | Oberfläche (Spielsuche, Sprechknopf, Antwort mit Zitat) |
| `tools/neues-spiel.sh` | PDF → bereinigtes Markdown |
| `tools/clean_md.py` | Bereinigung (wiederholte Überschriften, Bild-Platzhalter) |
| `tools/check_coverage.py` | findet Seiten, die Docling verloren hat |
| `tools/ask.py` | System-Prompt und Kommandozeilen-Test |
| `regelwerke/` | PDFs, bereinigtes Markdown (`*.md`), Docling-Rohausgabe (`*.docling.md`), `spiele.json` |
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
änderbar). Das native Ollama-Paket ist installiert, aber deaktiviert:
`sudo systemctl enable --now ollama` würde es wieder starten – dann vorher
`docker compose down`, sonst kollidiert Port 11434.

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
- **Gleichzeitige Fragen** werden nacheinander beantwortet; bei 3 Tischen
  gleichzeitig dauert die letzte Antwort ~10 s.

## Lizenz

GPL-3.0, siehe [LICENSE](LICENSE). Regelhefte gehören nicht zum Projekt und
sind nicht im Repository – sie unterliegen dem Urheberrecht ihrer Verlage.
