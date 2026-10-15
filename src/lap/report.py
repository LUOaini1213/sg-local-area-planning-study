"""Render report/brief.md to report/brief.pdf (A4) via HTML and a headless Chromium-family browser.

The markdown is the source of truth and is written by hand; this step only typesets it. A browser is looked up in
the usual Windows and Linux locations, or taken from the BROWSER_BIN environment variable. Without one the PDF step
is skipped with a message (CI does not build the PDF; the committed PDF is built locally).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown

from .config import ROOT

REPORT = ROOT / "report"
CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 9.3pt; line-height: 1.38;
       color: #1d1d1b; }
h1 { font-size: 17pt; margin: 0 0 2pt 0; color: #0b0b0b; }
h2 { font-size: 12pt; margin: 14pt 0 4pt 0; padding-bottom: 2pt; border-bottom: 1.2pt solid #1c5cab;
     color: #0b0b0b; page-break-after: avoid; }
p { margin: 0 0 6pt 0; }
ul, ol { margin: 0 0 6pt 0; padding-left: 16pt; }
li { margin-bottom: 2pt; }
table { border-collapse: collapse; margin: 4pt 0 8pt 0; font-size: 8.6pt; page-break-inside: avoid; }
th, td { border-bottom: 0.6pt solid #d4d2cc; padding: 2.5pt 6pt; text-align: left; vertical-align: top; }
th { border-bottom: 1pt solid #52514e; }
img { max-width: 100%; max-height: 98mm; width: auto; display: block; margin: 4pt auto 0 auto; page-break-inside: avoid; }
p:has(> img) { page-break-inside: avoid; margin-bottom: 2pt; }
.cap { font-size: 8pt; color: #52514e; margin: 2pt 0 8pt 0; text-align: center; }
code { font-size: 8.4pt; }
"""


def to_html(md_text):
    html = markdown.markdown(md_text, extensions=["tables", "sane_lists"])
    # turn each image's alt text into a visible caption
    import re
    html = re.sub(r'<p><img alt="([^"]*)" src="([^"]*)" /></p>',
                  r'<p><img alt="\1" src="\2" /></p><p class="cap">\1</p>', html)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>"


def browser():
    cands = [os.environ.get("BROWSER_BIN"),
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome")]
    return next((c for c in cands if c and Path(c).exists()), None)


def build():
    md = (REPORT / "brief.md").read_text(encoding="utf-8")
    html_path = REPORT / "brief.html"
    html_path.write_text(to_html(md), encoding="utf-8")
    exe = browser()
    if not exe:
        print("no headless browser found; brief.html written, PDF skipped")
        return None
    out = REPORT / "brief.pdf"
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([exe, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--no-pdf-header-footer",
                        f"--print-to-pdf={out}", html_path.as_uri()], check=True, timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    html_path.unlink()
    return out


if __name__ == "__main__":
    print(build())
