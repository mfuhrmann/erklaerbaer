# Symbol-Experimente (Stand 2026-10-27, unfertig)

Ziel: Bildsymbole im Fließtext (z. B. Gunsen: Blut, Stärke, Rüstung) beim Import
automatisch benennen und mit `tools/symbole.py` als unsichtbaren Text ins PDF schreiben.

Aufruf jeweils mit `uv run --no-project --with pymupdf --with httpx --with pillow --with numpy python <skript>`.

- `scan_icons.py <pdf>...` – zählt Bilder in Textzeilen pro Regelheft (überzählt bei
  zerlegten Grafiken, z. B. Age of Galaxy, Colt Express).
- `cluster_icons.py`, `unmapped.py` – Hilfen für die Zuordnung von Hand.
- `auto_label.py <pdf> <out.json> <hand.json>` – Text-LLM rät aus Kontext: 3/35 richtig → untauglich.
- `vision_label.py <pdf> <hand.json> <out.json>` – Bild-Modell gemma3:4b benennt Symbole,
  Vergleich mit Hand-Zuordnung (`regelwerke/gunsen.symbole.json`).
- `gunsen-original.pdf` – Gunsen ohne Symbol-Beschriftung (Testgrundlage).
