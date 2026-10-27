#!/usr/bin/env bash
# Convert a rulebook PDF into cleaned Markdown for the Erklärbär library.
# Usage: tools/neues-spiel.sh regelwerke/spiel.pdf
# Needs docling-serve, by default on http://127.0.0.1:5001 (DOCLING_URL).
set -euo pipefail

pdf="$1"
base="${pdf%.pdf}"
tools="$(dirname "$0")"
raw="$(mktemp)"
trap 'rm -f "$raw"' EXIT

curl -sSf -X POST "${DOCLING_URL:-http://127.0.0.1:5001}/v1/convert/file" \
  -F "files=@$pdf" -F to_formats=md -F image_export_mode=placeholder \
  -o "$raw"

python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
if d.get("status") != "success":
    sys.exit("docling: %s %s" % (d.get("status"), d.get("errors")))
open(sys.argv[2], "w", encoding="utf-8").write(d["document"]["md_content"])
' "$raw" "$base.docling.md"

python3 -I "$tools/clean_md.py" "$base.docling.md" "$base.md"
python3 -I "$tools/check_coverage.py" "$pdf" "$base.md"

echo "$base.md: $(wc -w < "$base.md") Wörter, $(grep -c '^#' "$base.md") Überschriften"
