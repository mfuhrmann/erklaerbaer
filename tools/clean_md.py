"""Clean up Markdown produced by docling from board game rulebooks."""
import html
import re
import sys

# Headings drawn with outline/shadow effects end up as the same text repeated
# many times ("RUNDENENDE RUNDENENDE ..."), collapse them to one occurrence.
REPEATED = re.compile(r"^(#+ )(.+?)(?: \2)+$", re.MULTILINE)
# Placeholders for images carry no information for the LLM.
IMAGE = re.compile(r"^<!-- image -->\n*", re.MULTILINE)


def clean(text):
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
