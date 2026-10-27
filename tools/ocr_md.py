"""Build rulebook Markdown from tesseract text files, one per page.

Usage: python3 ocr_md.py out.md page-1.txt page-2.txt ...
"""
import re
import sys

# Illustrations come out as short strings of symbols and stray letters.
LETTERS = re.compile(r"[A-Za-zÄÖÜäöüß]")


def is_text(line):
    line = line.strip()
    return len(line) >= 3 and len(LETTERS.findall(line)) >= 0.6 * len(line.replace(" ", ""))


def page_markdown(number, text):
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if is_text(line)]
        if lines:
            # Join hyphenated line breaks ("Spiel-\nfeld"), then the rest.
            paragraphs.append(re.sub(r"(\w)-\n(\w)", r"\1\2", "\n".join(lines)).replace("\n", " "))
    return f"## Seite {number}\n\n" + "\n\n".join(paragraphs)


if __name__ == "__main__":
    pages = [open(path, encoding="utf-8").read() for path in sys.argv[2:]]
    markdown = "\n\n".join(page_markdown(n, text) for n, text in enumerate(pages, start=1))
    open(sys.argv[1], "w", encoding="utf-8").write(markdown + "\n")
