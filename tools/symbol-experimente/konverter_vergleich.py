# konverter_vergleich.py <outdir> <game>... : docling vs pymupdf4llm on rulebook PDFs
# Coverage: share of the PDF's three-word runs (pdftotext) found in the raw
# Markdown, before tools/check_coverage.py appends lost pages.
import re, sys, time
from pathlib import Path

import httpx
import pymupdf4llm

sys.path.insert(0, "/home/mf1045/projects/erklaerbaer")
from tools.check_coverage import page_count, page_text, words

RULES = Path("/home/mf1045/projects/erklaerbaer/regelwerke")
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def docling(pdf):
    with open(pdf, "rb") as f:
        r = httpx.post("http://127.0.0.1:5001/v1/convert/file", timeout=900,
                       files={"files": (pdf.name, f, "application/pdf")},
                       data={"to_formats": "md", "image_export_mode": "placeholder"}).json()
    return r["document"]["md_content"]


def stats(md, pdf_runs):
    runs = words(md)
    return (len(pdf_runs & runs) / len(pdf_runs), len(re.findall(r"^#+ ", md, re.M)),
            len(re.findall(r"^\|.*\|\s*$", md, re.M)), len(re.findall(r"\[[^\]\n]{2,30}\]", md)), len(md))


print(f"{'Spiel':28} {'':10} {'Vollst.':>7} {'Übers.':>6} {'Tab.Z.':>6} {'Symb.':>5} {'Zeichen':>8} {'Zeit':>6}")
for game in sys.argv[2:]:
    pdf = RULES / f"{game}.pdf"
    pdf_runs = set()
    for p in range(1, page_count(str(pdf)) + 1):
        pdf_runs |= words(page_text(str(pdf), p))
    for name, convert in (("docling", docling), ("pymupdf4llm", lambda p: pymupdf4llm.to_markdown(str(p), show_progress=False))):
        t = time.time()
        md = convert(pdf)
        seconds = time.time() - t
        (out / f"{game}.{name}.md").write_text(md, encoding="utf-8")
        cov, heads, tables, symbols, chars = stats(md, pdf_runs)
        print(f"{game[:28]:28} {name:10} {cov:7.0%} {heads:6d} {tables:6d} {symbols:5d} {chars:8d} {seconds:5.0f}s", flush=True)
