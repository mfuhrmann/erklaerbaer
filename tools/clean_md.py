"""Clean up Markdown converted from board game rulebooks (pymupdf4llm, docling)."""
import html
import re
import sys

# Headings drawn with outline/shadow effects end up as the same text repeated
# many times ("RUNDENENDE RUNDENENDE ..."), collapse them to one occurrence.
REPEATED = re.compile(r"^(#+ )(.+?)(?: \2)+$", re.MULTILINE)
# Placeholders for images carry no information for the LLM.
IMAGE = re.compile(r"^<!-- image -->\n*", re.MULTILINE)
# pymupdf4llm reads text inside pictures (labels in a diagram: useful; often
# just OCR noise like "- s ad -").
PICTURE_TEXT = re.compile(r"<!-- Start of picture text -->(.*?)<!-- End of picture text -->", re.DOTALL)
REAL_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")


def picture_text(match):
    text = re.sub(r"\s+", " ", match.group(1).replace("<br>", " / ")).strip(" /")
    return f"(Bildtext: {text})" if len(REAL_WORD.findall(text)) >= 2 else ""


def clean(text):
    text = PICTURE_TEXT.sub(picture_text, text)
    # Docling escapes &, < and > as HTML entities.
    text = html.unescape(text)
    text = REPEATED.sub(r"\1\2", text)
    return IMAGE.sub("", text)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        text = f.read()
    with open(dst, "w", encoding="utf-8") as f:
        f.write(clean(text))
