"""Convert a rulebook PDF to Markdown with pymupdf4llm.

Usage: python3 tools/pdf_md.py RULEBOOK.pdf OUT.md

Replaced docling (2026-10): on 12 rulebooks it kept more of the text (81% vs
76% of the PDF's word runs; Tax The Rich 88% vs 21%), kept the invisible
symbol names (Gunsen: 142 vs 16), was 2-3x faster and needs no separate
service; answers on 28 test questions: 56/56 vs 55/56.
"""
import re
import sys

import pymupdf
import pymupdf4llm

# pymupdf4llm sometimes puts bold markers inside a word and splits it:
# "Ent **erhaken! In** Wirklichkeit" for "Enterhaken! In Wirklichkeit".
SPLIT_AT_BOLD = re.compile(r"(\w+) \*\*(\w+)|(\w+)\*\* (\w+)")


def to_markdown(pdf):
    markdown = pymupdf4llm.to_markdown(pdf, show_progress=False)
    vocabulary = {w.lower() for page in pymupdf.open(pdf) for w in re.findall(r"\w+", page.get_text())}

    def join(match):
        left, right = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        word = left + right
        # A part that is no word of its own (or just a stray syllable like "en").
        broken = any(part.lower() not in vocabulary or len(part) <= 2 for part in (left, right))
        return word if word.lower() in vocabulary and broken else match.group(0)

    markdown = SPLIT_AT_BOLD.sub(join, markdown)
    # Bold means nothing to the model.
    return markdown.replace("**", "")


if __name__ == "__main__":
    open(sys.argv[2], "w", encoding="utf-8").write(to_markdown(sys.argv[1]))
