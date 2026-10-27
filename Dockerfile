FROM python:3.12-slim

# pdftotext/pdfinfo: find the PDF page a quote comes from.
# poppler-data: CJK font encodings; without it pdftotext/pdftoppm silently drop
# text set in e.g. Japanese fonts (Cena) and the PDF looks like an empty scan.
# curl, tesseract, imagemagick: importing rulebooks (tools/neues-spiel.sh, tools/ocr-spiel.sh).
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils poppler-data curl \
       tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng imagemagick \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY tools ./tools

# Rulebooks and logs are mounted from the host, so new games need no rebuild.
VOLUME ["/srv/regelwerke", "/srv/logs"]
EXPOSE 8090
CMD ["/srv/.venv/bin/uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8090"]
