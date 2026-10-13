"""Reading the input CSV and building consistent file names.

This module replaces the ``build_output_path`` function that used to live in
``scrape_whitepapers.py`` and was imported by ``analyze_themes.py`` (which
forced the analysis stage to import requests / BeautifulSoup).  All stages
now share this one lightweight module.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from dateutil import parser as dateparser

NO_DATE_TOKENS = {"", "n.d.", "nd", "not specified", "rolling/current", "rolling", "current", "tbd"}


def sanitize(text: str, max_length: int = 60) -> str:
    """Make *text* safe for a file or folder name."""
    if not text:
        return "untitled"
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:max_length] or "untitled"


def shorten_title(title: str, max_words: int = 8) -> str:
    return sanitize(" ".join(title.split()[:max_words]))


def parse_publish_date(raw: Optional[str]) -> str:
    """Normalise the messy ``Publish_date`` column to a sortable string.

    Handles every pattern found in the real data set::

        '06/23/2026' -> 2026-06-23     'Jan 29, 2026' -> 2026-01-29
        'Jan 2026'   -> 2026-01        'Sept 2025'    -> 2025-09
        'Q4 2025'    -> 2025-Q4        '2025/2026'    -> 2025-2026
        '2026'       -> 2026           'n.d.', 'Not specified', 'Rolling/current' -> nodate
    """
    if raw is None:
        return "nodate"
    raw = raw.strip()
    if raw.lower() in NO_DATE_TOKENS:
        return "nodate"
    m = re.fullmatch(r"(?i)q([1-4])\s*[-/ ]?\s*((?:19|20)\d{2})", raw)
    if m:
        return f"{m.group(2)}-Q{m.group(1)}"
    m = re.fullmatch(r"((?:19|20)\d{2})\s*[/-]\s*((?:19|20)\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if re.fullmatch(r"(?:19|20)\d{2}", raw):
        return raw
    try:
        # Parse twice with different defaults; a field that changes between the
        # two parses was NOT present in the text, so we do not invent it.
        a = dateparser.parse(raw, default=datetime(2000, 1, 1))
        b = dateparser.parse(raw, default=datetime(2001, 2, 2))
        if a.year != b.year:
            raise ValueError("no year")
        if a.month != b.month:
            return f"{a.year}"
        if a.day != b.day:
            return f"{a.year}-{a.month:02d}"
        return a.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        pass
    m = re.search(r"\b(?:19|20)\d{2}\b", raw)
    return m.group(0) if m else "nodate"


@dataclass(frozen=True)
class Paper:
    row: int
    firm: str
    title: str
    url: str
    publish_date: str      # raw value from the CSV
    category: str

    @property
    def firm_dir(self) -> str:
        return sanitize(self.firm, 40)

    @property
    def stem(self) -> str:
        """``{firm}_{date}_{short-title}_{hash}`` - unique per CSV row.

        The 6-character hash (of firm+title+url) fixes a bug in the original
        naming scheme where two papers with the same first eight title words
        and the same date would collide.
        """
        h = hashlib.md5(f"{self.firm}|{self.title}|{self.url}".encode()).hexdigest()[:6]
        return f"{self.firm_dir}_{parse_publish_date(self.publish_date)}_{shorten_title(self.title)}_{h}"

    def raw_path(self, raw_dir: Path, suffix: str = ".html") -> Path:
        return raw_dir / self.firm_dir / f"{self.stem}{suffix}"

    def text_path(self, text_dir: Path) -> Path:
        return text_dir / self.firm_dir / f"{self.stem}.txt"

    def find_raw(self, raw_dir: Path) -> Optional[Path]:
        for suffix in (".html", ".pdf"):
            p = self.raw_path(raw_dir, suffix)
            if p.exists():
                return p
        return None


def load_papers(csv_path, limit: Optional[int] = None) -> list:
    """Read the input CSV (tolerates stray spaces / BOM in headers)."""
    papers = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [n.strip().lower() for n in (reader.fieldnames or [])]
        needed = {"firm", "title", "url", "publish_date", "trend_category"}
        missing = needed - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV is missing column(s): {sorted(missing)}")
        for i, r in enumerate(reader, start=1):
            papers.append(Paper(i, r["firm"].strip(), r["title"].strip(), r["url"].strip(),
                                (r["publish_date"] or "").strip(), r["trend_category"].strip()))
    return papers[:limit] if limit else papers
