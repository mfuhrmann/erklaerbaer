"""Small card (A7) with a QR code to the Erklärbär, to put on the table at game nights.

    uv run --with qrcode tools/qr-karte.py [URL] [OUTPUT.pdf]

Default URL: the HTTPS address of this laptop (the microphone works only
there), with the LAN address it uses now. Check it before you print: in a
different network the laptop has a different address. The card is printed on
A4 with a dashed cut line; Chromium makes the PDF.
"""
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import qrcode
import qrcode.image.svg



def lan_address():
    """Address of the interface with the default route. A UDP connect sends no packet."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # TEST-NET-1, only selects the route
        return s.getsockname()[0]


url = (sys.argv[1] if len(sys.argv) > 1 else "") or f"https://{lan_address()}:8443"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "erklaerbaer-karte.pdf").resolve()

# Error level M: still readable with small stains or a fold.
qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
qr.add_data(url)
svg = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode")
address = url.removeprefix("https://").removeprefix("http://")
warning = (
    "Warnt der Browser: „Erweitert“ → „Weiter“."
    if url.startswith("https://") else ""
)

page = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 0; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; color: #2b2118; }}
  .card {{
    width: 74mm; height: 105mm; margin: 15mm auto 0; box-sizing: border-box;
    border: 0.3mm dashed #b8a998; border-radius: 3mm; padding: 6mm 6mm 5mm;
    display: flex; flex-direction: column; align-items: center; text-align: center;
    background: #faf6f0;
  }}
  .bear {{ font-size: 15mm; line-height: 1; font-family: "Noto Color Emoji", sans-serif; }}
  h1 {{ margin: 1.5mm 0 0; font-size: 7mm; letter-spacing: .2mm; }}
  .claim {{ margin: 1mm 0 3.5mm; font-size: 3.4mm; color: #7a6a5a; }}
  .qr {{ width: 38mm; height: 38mm; padding: 2.5mm; background: #fff; border-radius: 2mm; }}
  .qr svg {{ width: 100%; height: 100%; display: block; }}
  .address {{ margin: 3mm 0 0; font-size: 3.6mm; font-weight: 700; color: #b5652b; }}
  .hint {{ margin: auto 0 0; font-size: 2.6mm; line-height: 1.35; color: #7a6a5a; }}
</style></head><body>
  <div class="card">
    <div class="bear">🐻</div>
    <h1>Erklärbär</h1>
    <p class="claim">Regelfrage? Frag den Bären.</p>
    <div class="qr">{svg}</div>
    <p class="address">{address}</p>
    <p class="hint">Im WLAN scannen, Spiel wählen, fragen.<br>{warning}</p>
  </div>
</body></html>"""

with tempfile.TemporaryDirectory() as folder:
    html = Path(folder) / "karte.html"
    html.write_text(page, encoding="utf-8")
    subprocess.run(["chromium", "--headless", "--no-pdf-header-footer", f"--print-to-pdf={out}",
                    html.as_uri()], check=True, capture_output=True)
print(f"{url} -> {out}")
