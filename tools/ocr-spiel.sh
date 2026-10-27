#!/usr/bin/env bash
# OCR a rulebook whose PDF has no usable text layer (scans, fonts as outlines).
# Usage: tools/ocr-spiel.sh regelwerke/spiel.pdf [sprache] [negativ]
#   sprache: tesseract language, default deu
#   negativ: invert pages first (light text on dark background)
# Replaces the PDF with a searchable one (for the page links) and writes
# spiel.md from tesseract's own text, which keeps columns in order. Docling
# lost up to two thirds of the text on such PDFs.
set -euo pipefail

pdf="$1"
lang="${2:-deu}"
base="${pdf%.pdf}"
tools="$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# ImageMagick 7 is "magick", Debian's ImageMagick 6 (in the container) "convert".
imagemagick="$(command -v magick || command -v convert)"

pdftoppm -r 300 -png "$pdf" "$work/p"
for page in "$work"/p-*.png; do
    [ "${3:-}" = negativ ] && "$imagemagick" "$page" -negate "$page"
    tesseract "$page" "${page%.png}" -l "$lang" txt pdf 2>/dev/null
done

pdfunite "$work"/p-*.pdf "$work/ocr.pdf"
mv "$work/ocr.pdf" "$pdf"
python3 -I "$tools/ocr_md.py" "$base.md" "$work"/p-*.txt

echo "$base.md: $(wc -w < "$base.md") Wörter (OCR)"
