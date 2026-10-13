"""Central configuration: paths, thresholds and the theme lexicons.

Everything you are likely to tweak lives here so the other modules contain
logic only.  Paths are derived from a single ``workdir`` so the same code can
write to ``output/`` (real run) or a temp folder (demo / tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------
MIN_WORDS = 150            # pages with fewer words are flagged / excluded
MIN_TEXT_CHARS = 400       # raw HTML with less visible text = "JS shell"
REQUEST_TIMEOUT = 25       # seconds, plain `requests` download
PLAYWRIGHT_TIMEOUT_MS = 30_000
MAX_RETRIES = 3
MIN_WAIT, MAX_WAIT = 2.0, 3.0   # polite delay between rows (seconds)
TOP_N_TERMS = 15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# Theme lexicons.  Keys MUST equal the values of the CSV column
# `Trend_category`, so the lexicons can be validated against the human labels.
# --------------------------------------------------------------------------
LEXICONS: dict[str, list[str]] = {
    "Enterprise / Agentic AI Adoption": [
        "artificial intelligence", "generative ai", "gen ai", "genai", "agentic", "ai agents",
        "ai agent", "machine learning", "automation", "llm", "llms", "copilot", "ai",
    ],
    "Future of Finance & Work": [
        "cfo", "cfos", "finance function", "workforce", "talent", "skills", "operating model",
        "transformation", "productivity", "future of work", "human capital", "reskilling",
    ],
    "Cybersecurity & Risk": [
        "cyber", "cybersecurity", "ransomware", "resilience", "threat", "threats", "risk",
        "risks", "breach", "compliance", "governance", "vulnerability",
    ],
    "M&A and Deal Activity": [
        "m&a", "merger", "mergers", "acquisition", "acquisitions", "divestiture", "divestitures",
        "private equity", "deal", "deals", "valuation", "dealmaking", "carve-out", "ipo",
    ],
    "ESG & Climate Disclosure": [
        "esg", "sustainability", "climate", "carbon", "emissions", "net zero", "csrd",
        "disclosure", "decarbonization", "issb", "scope 3",
    ],
}

SHORT_LABELS = {
    "Enterprise / Agentic AI Adoption": "AI & Agentic",
    "Future of Finance & Work": "Finance & Work",
    "Cybersecurity & Risk": "Cyber & Risk",
    "M&A and Deal Activity": "M&A & Deals",
    "ESG & Climate Disclosure": "ESG & Climate",
}

# Words that identify the publisher or the website, not the content.  They are
# removed before the TF-IDF "distinctive terms" step.
BOILERPLATE_WORDS = {
    "deloitte", "kpmg", "pwc", "pricewaterhousecoopers", "ey", "ernst", "young", "llp",
    "touche", "tohmatsu", "www", "com", "http", "https", "html", "pdf", "cookie", "cookies",
    "privacy", "terms", "subscribe", "newsletter", "linkedin", "twitter", "facebook",
    "download", "read", "share", "click", "contact", "insights", "member", "firms", "network",
    "global", "limited", "legal", "copyright", "rights", "reserved",
}


@dataclass
class Settings:
    """Run-time settings.  Create one and pass it to every stage."""

    csv_path: Path = ROOT / "data" / "INPUT_CSV.csv"
    workdir: Path = ROOT / "output"
    min_words: int = MIN_WORDS
    use_playwright: bool = True
    delay: tuple = (MIN_WAIT, MAX_WAIT)

    def __post_init__(self) -> None:
        self.csv_path = Path(self.csv_path)
        self.workdir = Path(self.workdir)

    @property
    def raw_dir(self) -> Path: return self.workdir / "raw"
    @property
    def text_dir(self) -> Path: return self.workdir / "extracted_text"
    @property
    def table_dir(self) -> Path: return self.workdir / "extracted_tables"
    @property
    def analysis_dir(self) -> Path: return self.workdir / "analysis"
    @property
    def scrape_manifest(self) -> Path: return self.workdir / "scrape_manifest.csv"
    @property
    def failed_csv(self) -> Path: return self.workdir / "failed_saves.csv"
    @property
    def extract_manifest(self) -> Path: return self.workdir / "extraction_manifest.csv"
    @property
    def report_pdf(self) -> Path: return self.workdir / "BTLI_Project_Report.pdf"

    def ensure(self) -> None:
        for p in (self.raw_dir, self.text_dir, self.table_dir, self.analysis_dir):
            p.mkdir(parents=True, exist_ok=True)
