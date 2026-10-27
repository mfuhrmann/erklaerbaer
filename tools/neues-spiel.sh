#!/usr/bin/env bash
# Convert a rulebook PDF into cleaned Markdown for the Erklärbär library.
# Usage: tools/neues-spiel.sh regelwerke/spiel.pdf
# Needs pymupdf4llm: run it in the app container or with `uv run`.
set -euo pipefail

pdf="$1"
base="${pdf%.pdf}"
tools="$(dirname "$0")"

python3 -I "$tools/pdf_md.py" "$pdf" "$base.roh.md"
python3 -I "$tools/clean_md.py" "$base.roh.md" "$base.md"
python3 -I "$tools/check_coverage.py" "$pdf" "$base.md"

echo "$base.md: $(wc -w < "$base.md") Wörter, $(grep -c '^#' "$base.md") Überschriften"
