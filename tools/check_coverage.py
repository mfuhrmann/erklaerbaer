"""Find PDF pages that docling dropped and append their raw text.

Usage: python3 -I tools/check_coverage.py RULEBOOK.pdf RULEBOOK.md

Docling sometimes treats a whole page as a picture and returns no text for
it. For every page, compare the words pdftotext finds with the Markdown; if
too few of them made it, append the raw page text so the rules are not lost.
"""
import re
import subprocess
import sys

MIN_COVERAGE = 0.6
MIN_WORDS = 20
# "[Blut]": a symbol name from tools/symbole.py. Its word gets a marker
# prefix, so the word runs around symbols can be picked out.
SYMBOL = re.compile(r"\[([^\]\n]{2,40})\]")
SYMBOL_MARK = "zzsymbol"


def words(text):
    # Ligatures and soft hyphens split words differently in both tools, so
    # compare lowercased words without punctuation. Single words like
    # "Punkte" occur on every page, so compare runs of three words instead.
    text = text.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    tokens = re.findall(r"\w{2,}", text.lower())
    return {" ".join(tokens[i:i + 3]) for i in range(len(tokens) - 2)}


def page_count(pdf):
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True)
    return int(re.search(r"^Pages:\s+(\d+)", info.stdout, re.MULTILINE).group(1))


def page_text(pdf, page):
    return subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), pdf, "-"],
        capture_output=True, text=True, check=True,
    ).stdout


def main():
    pdf, md_path = sys.argv[1], sys.argv[2]
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    md_words = words(md)

    missing = []
    for page in range(1, page_count(pdf) + 1):
        text = page_text(pdf, page)
        page_words = words(text)
        if len(page_words) < MIN_WORDS:
            continue
        coverage = len(page_words & md_words) / len(page_words)
        # Symbol names written into the PDF (tools/symbole.py) are invisible
        # text, which docling sometimes drops; the sentences then lose them.
        symbol_runs = {run for run in words(SYMBOL.sub(lambda m: f" {SYMBOL_MARK}{m.group(1)} ", text))
                       if SYMBOL_MARK.lower() in run}
        symbol_runs = {run.replace(SYMBOL_MARK.lower(), "") for run in symbol_runs}
        symbols_kept = len(symbol_runs & md_words) / len(symbol_runs) if symbol_runs else 1
        if coverage < MIN_COVERAGE:
            print(f"WARNUNG: Seite {page} nur zu {coverage:.0%} erkannt, Rohtext angehängt")
            missing.append((page, text))
        elif symbols_kept < MIN_COVERAGE:
            print(f"WARNUNG: Seite {page}: Symbole nur zu {symbols_kept:.0%} übernommen, Rohtext angehängt")
            missing.append((page, text))

    if missing:
        with open(md_path, "a", encoding="utf-8") as f:
            for page, text in missing:
                f.write(f"\n\n## Seite {page} (Rohtext, Layout nicht erkannt)\n\n{text.strip()}\n")


if __name__ == "__main__":
    main()
