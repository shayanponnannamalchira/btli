"""Stage 1 - download every URL in the CSV (HTML *and* PDF).

Improvements over the original ``scrape_whitepapers.py``:
  * PDFs are detected (Content-Type / %PDF magic bytes) and saved as .pdf
    instead of being corrupted into .html (16 of the 200 URLs are PDFs).
  * One Playwright browser is started once and reused (was: one per page).
  * Retries with exponential back-off on 429 / 5xx / network errors.
  * Playwright waits for ``domcontentloaded`` then *tries* ``networkidle``
    (the old ``networkidle``-only wait timed out on analytics-heavy pages).
  * Encoding is repaired when the server omits a charset.
  * A full ``scrape_manifest.csv`` is written (not just failures), so later
    stages and the report can compute coverage.
"""
from __future__ import annotations

import csv
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from . import config
from .papers import Paper, load_papers

log = logging.getLogger("btli.scrape")


@dataclass
class FetchResult:
    ok: bool
    kind: str = ""            # "html" | "pdf"
    data: object = b""        # str for html, bytes for pdf
    method: str = ""          # "requests" | "playwright"
    error: str = ""


def visible_text_length(html) -> int:
    """Characters of human-visible text left after removing scripts/styles."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return len(soup.get_text(separator=" ", strip=True))


class Browser:
    """Lazy, reusable headless Chromium (only started if actually needed)."""

    def __init__(self) -> None:
        self._pw = self._browser = self._ctx = None

    def _start(self) -> None:
        from playwright.sync_api import sync_playwright   # imported lazily
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(user_agent=config.USER_AGENT)

    def get_html(self, url: str) -> FetchResult:
        try:
            if self._ctx is None:
                self._start()
            page = self._ctx.new_page()
            try:
                page.goto(url, timeout=config.PLAYWRIGHT_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:      # noisy pages never go idle - that is fine
                    pass
                return FetchResult(True, "html", page.content(), "playwright")
            finally:
                page.close()
        except Exception as e:          # noqa: BLE001 - Playwright raises many types
            return FetchResult(False, error=f"playwright: {e}"[:300])

    def close(self) -> None:
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            try:
                if obj:
                    getattr(obj, meth)()
            except Exception:           # noqa: BLE001
                pass


class Fetcher:
    def __init__(self, use_playwright: bool = True) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT,
                                     "Accept-Language": "en-US,en;q=0.9"})
        self.use_playwright = use_playwright
        self.browser = Browser()

    def close(self) -> None:
        self.browser.close()
        self.session.close()

    # -- attempt 1 ----------------------------------------------------------
    def via_requests(self, url: str) -> FetchResult:
        last = ""
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                r = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < config.MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "").lower()
                if "pdf" in ctype or r.content[:5] == b"%PDF-":
                    return FetchResult(True, "pdf", r.content, "requests")
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding or "utf-8"
                return FetchResult(True, "html", r.text, "requests")
            except requests.HTTPError as e:
                last = str(e)
                if e.response is not None and e.response.status_code < 500 and e.response.status_code != 429:
                    break                         # 403/404: retrying will not help
            except requests.RequestException as e:
                last = str(e)
            if attempt < config.MAX_RETRIES:
                time.sleep(2 ** attempt)
        return FetchResult(False, error=f"requests: {last}"[:300])

    # -- orchestration ------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        res = self.via_requests(url)
        if not res.ok and self.use_playwright:
            log.info("    requests failed (%s) -> trying browser", res.error[:80])
            res = self.browser.get_html(url) if self.use_playwright else res
        if res.ok and res.kind == "html":
            n = visible_text_length(res.data)
            if n < config.MIN_TEXT_CHARS and self.use_playwright and res.method != "playwright":
                log.info("    page looks empty (%d chars) -> trying browser", n)
                pw = self.browser.get_html(url)
                if pw.ok and visible_text_length(pw.data) > n:
                    res = pw
        return res


MANIFEST_FIELDS = ["row", "firm", "title", "url", "publish_date", "trend_category", "stem",
                   "status", "method", "kind", "visible_chars", "path", "reason"]


def run(settings: config.Settings, papers: Optional[list] = None, limit: Optional[int] = None) -> list:
    """Download all papers; returns the manifest rows (also written to disk)."""
    papers = papers if papers is not None else load_papers(settings.csv_path, limit)
    settings.ensure()
    fetcher = Fetcher(settings.use_playwright)
    manifest = []
    try:
        for i, p in enumerate(papers, start=1):
            log.info("[%d/%d] %s - %s", i, len(papers), p.firm, p.title[:60])
            row = {"row": p.row, "firm": p.firm, "title": p.title, "url": p.url,
                   "publish_date": p.publish_date, "trend_category": p.category, "stem": p.stem,
                   "status": "", "method": "", "kind": "", "visible_chars": "", "path": "", "reason": ""}
            manifest.append(row)
            existing = p.find_raw(settings.raw_dir)
            try:
                if existing:                                   # resume support
                    row.update(status="cached", method="cache", kind=existing.suffix[1:],
                               path=str(existing))
                    if existing.suffix == ".html":
                        row["visible_chars"] = visible_text_length(existing.read_text("utf-8", "ignore"))
                    continue
                if not p.url:
                    row.update(status="failed", reason="No URL provided")
                    continue
                res = fetcher.fetch(p.url)
                if not res.ok:
                    row.update(status="failed", reason=res.error)
                    continue
                if res.kind == "pdf":
                    path = p.raw_path(settings.raw_dir, ".pdf")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(res.data)
                else:
                    path = p.raw_path(settings.raw_dir, ".html")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(res.data, encoding="utf-8")
                    row["visible_chars"] = visible_text_length(res.data)
                row.update(status="saved", method=res.method, kind=res.kind, path=str(path))
                if res.kind == "html" and row["visible_chars"] < config.MIN_TEXT_CHARS:
                    row.update(status="thin", reason=f"only {row['visible_chars']} visible chars")
            except Exception as e:                              # noqa: BLE001
                row.update(status="failed", reason=f"unexpected: {e}"[:300])
            finally:
                if not existing:
                    time.sleep(random.uniform(*settings.delay))   # be polite
    finally:
        fetcher.close()
        write_manifest(settings, manifest)
    return manifest


def write_manifest(settings: config.Settings, manifest: list) -> None:
    with open(settings.scrape_manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(manifest)
    bad = [r for r in manifest if r["status"] in ("failed", "thin")]
    with open(settings.failed_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(bad)
    ok = sum(r["status"] in ("saved", "cached") for r in manifest)
    log.info("Download finished: %d ok, %d need attention -> %s", ok, len(bad), settings.failed_csv)
