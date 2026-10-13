"""Offline demo / test-data generator.

Creates a SYNTHETIC raw corpus for every row of the CSV so the whole pipeline
can be exercised without internet access.  The texts are random sentences
built from the theme lexicons plus invented "signature" words per firm
(e.g. ``deloitte-sig`` words), so the analysis can be checked by asking:
*does it recover the signal we planted?*   NOTHING here is real firm content.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from . import config
from .papers import load_papers

# Invented marker words: if the TF-IDF stage works they must surface for the right firm.
SIGNATURES = {
    "Deloitte": ["zorbix", "quantaflow", "helvarion", "drumlinet", "oxmerge", "pelagiq"],
    "KPMG": ["krestal", "tamborine", "velquist", "norvane", "ibixor", "fandrel"],
    "PWC": ["pyrelle", "wombatic", "slaterra", "cobriel", "hexavant", "turmalin"],
    "EY": ["eburnic", "lumotek", "yarrowind", "stelvane", "ombrelle", "vexcrypt"],
}
# Planted emphasis: multiplier on how often a firm drifts to a theme outside its labelled category.
TILT = {"Deloitte": 0, "KPMG": 2, "PWC": 3, "EY": 4}   # index into LEXICONS keys

FILLER = ("organisations leaders strategy board market growth customers investment outlook "
          "survey respondents expect plan change pressure regulators leadership priorities "
          "results evidence practice capability roadmap insight sector outcomes budget").split()


def _paragraph(rng, firm, category, n_words):
    themes = list(config.LEXICONS)
    tilt_theme = themes[TILT.get(firm, 0)]
    words = []
    while len(words) < n_words:
        r = rng.random()
        if r < 0.045:
            words.append(rng.choice(config.LEXICONS[category]))
        elif r < 0.085:
            words.append(rng.choice(config.LEXICONS[tilt_theme]))
        elif r < 0.115:
            words.append(rng.choice(config.LEXICONS[rng.choice(themes)]))
        elif r < 0.13:
            words.append(rng.choice(SIGNATURES.get(firm, ["unknownsig"])))
        else:
            words.append(rng.choice(FILLER))
        if rng.random() < 0.07:
            words[-1] += "."
    text = " ".join(words)
    return text[0].upper() + text[1:] + "."


def _html(rng, p, thin):
    nav = "<nav><a href='/'>Home</a> <a href='/insights'>Insights</a> Cookie settings Subscribe</nav>"
    footer = "<footer>Copyright All rights reserved Privacy Terms of use Contact us</footer>"
    if thin:       # a JavaScript shell: almost no visible text
        return f"<html><head><title>{p.title}</title><script>var app=1;</script></head><body><div id='root'></div></body></html>"
    body = "".join(f"<p>{_paragraph(rng, p.firm, p.category, rng.randint(60, 140))}</p>"
                   for _ in range(rng.randint(5, 9)))
    table = ("<table><tr><th>Metric</th><th>Value</th></tr>"
             f"<tr><td>Respondents</td><td>{rng.randint(100, 3000)}</td></tr>"
             f"<tr><td>Share planning change</td><td>{rng.randint(10, 90)}%</td></tr></table>")
    return (f"<html><head><title>{p.title}</title></head><body>{nav}<article><h1>{p.title}</h1>"
            f"{body}{table}</article>{footer}</body></html>")


def _pdf(path: Path, text: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in __import__("textwrap").wrap(text, 95):
        c.drawString(40, y, line); y -= 14
        if y < 40:
            c.showPage(); y = 800
    c.save()


def generate(settings: config.Settings, seed: int = 7, limit=None, thin_rate: float = 0.06) -> int:
    rng = random.Random(seed)
    settings.ensure()
    papers = load_papers(settings.csv_path, limit)
    manifest = []
    for p in papers:
        is_pdf = p.url.lower().endswith(".pdf")
        thin = (not is_pdf) and rng.random() < thin_rate
        if is_pdf:
            path = p.raw_path(settings.raw_dir, ".pdf")
            path.parent.mkdir(parents=True, exist_ok=True)
            _pdf(path, " ".join(_paragraph(rng, p.firm, p.category, rng.randint(80, 160)) for _ in range(6)))
        else:
            path = p.raw_path(settings.raw_dir, ".html")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_html(rng, p, thin), encoding="utf-8")
        manifest.append({"row": p.row, "firm": p.firm, "title": p.title, "url": p.url,
                         "publish_date": p.publish_date, "trend_category": p.category, "stem": p.stem,
                         "status": "thin" if thin else "saved", "method": "synthetic",
                         "kind": "pdf" if is_pdf else "html", "visible_chars": "",
                         "path": str(path), "reason": "synthetic JS shell" if thin else ""})
    from .scrape import write_manifest
    write_manifest(settings, manifest)
    return len(papers)
