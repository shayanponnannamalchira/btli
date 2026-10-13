"""Stage 2 - turn raw HTML / PDF into clean text (+ tables as CSV).

Improvements over the original ``extract_html.py``:
  * Driven by the paper list (not a folder glob), so output names always
    match the analysis stage.
  * PDFs are read with pypdf.
  * The BeautifulSoup fallback that was only a comment is now real code and
    kicks in when trafilatura returns nothing or a very short result.
  * An ``extraction_manifest.csv`` records words / tables / flags per paper.
"""
from __future__ import annotations

import csv
import logging
import xml.etree.ElementTree as ET
from typing import Optional

import trafilatura
from bs4 import BeautifulSoup

from . import config
from .papers import Paper, load_papers

log = logging.getLogger("btli.extract")
logging.getLogger("trafilatura").setLevel(logging.ERROR)   # silence "discarding data" noise on empty pages

FIELDS = ["row", "firm", "title", "trend_category", "stem", "raw_file", "method",
          "words", "tables", "flag", "text_path"]


def _clean_cell(cell) -> str:
    return " ".join("".join(cell.itertext()).split())


def tables_from_xml(xml_string: str) -> list:
    """Every <table> in trafilatura's XML -> list of rows -> list of cells."""
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return []
    tables = []
    for table in root.iter("table"):
        rows = []
        for row in table.iter("row"):
            cells = [_clean_cell(c) for c in row if c.tag == "cell"]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def bs4_fallback(html) -> str:
    """Blunt backup: drop obvious chrome, keep <article>/<main>/<body> text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    box = soup.find("article") or soup.find("main") or soup.body
    return box.get_text(separator="\n", strip=True) if box else ""


def pdf_text(path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_html(raw: bytes):
    """Return (text, tables, method) for one HTML page."""
    text = trafilatura.extract(raw, output_format="txt", include_tables=False,
                               include_comments=False, include_links=False, favor_recall=True) or ""
    xml = trafilatura.extract(raw, output_format="xml", include_tables=True,
                              include_comments=False, favor_recall=True)
    tables = tables_from_xml(xml) if xml else []
    method = "trafilatura"
    if len(text.split()) < config.MIN_WORDS:
        alt = bs4_fallback(raw)
        if len(alt.split()) > len(text.split()):
            text, method = alt, "bs4-fallback"
    return text, tables, method


def run(settings: config.Settings, papers: Optional[list] = None, limit: Optional[int] = None) -> list:
    papers = papers if papers is not None else load_papers(settings.csv_path, limit)
    settings.ensure()
    out = []
    for i, p in enumerate(papers, start=1):
        rec = {"row": p.row, "firm": p.firm, "title": p.title, "trend_category": p.category,
               "stem": p.stem, "raw_file": "", "method": "", "words": 0, "tables": 0,
               "flag": "", "text_path": ""}
        out.append(rec)
        raw_path = p.find_raw(settings.raw_dir)
        if raw_path is None:
            rec["flag"] = "no_raw_file"
            continue
        rec["raw_file"] = str(raw_path)
        try:
            if raw_path.suffix == ".pdf":
                text, tables, method = pdf_text(raw_path), [], "pypdf"
            else:
                text, tables, method = extract_html(raw_path.read_bytes())
        except Exception as e:                                   # noqa: BLE001
            rec["flag"] = f"error: {e}"[:120]
            log.warning("[%d] %s failed: %s", i, p.stem, e)
            continue
        rec["method"] = method
        for n, rows in enumerate(tables, start=1):
            tpath = settings.table_dir / p.firm_dir / f"{p.stem}_table{n}.csv"
            tpath.parent.mkdir(parents=True, exist_ok=True)
            with open(tpath, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(rows)
        rec["tables"] = len(tables)
        words = len(text.split())
        rec["words"] = words
        if words == 0:
            rec["flag"] = "no_text"
            continue
        tp = p.text_path(settings.text_dir)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(text, encoding="utf-8")
        rec["text_path"] = str(tp)
        if words < settings.min_words:
            rec["flag"] = f"short ({words} words)" + (" - has tables" if tables else "")
    with open(settings.extract_manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    flagged = sum(bool(r["flag"]) for r in out)
    log.info("Extraction finished: %d papers, %d flagged -> %s", len(out), flagged, settings.extract_manifest)
    return out
