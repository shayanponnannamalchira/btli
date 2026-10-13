"""Stage 4 - build the PDF project report (reportlab).

The narrative sections (objectives, architecture, method, fixes, limitations)
are static; the data sections (input data, coverage, results) are computed
from the CSV and the files in <workdir>/analysis, so re-running the pipeline
on live data regenerates a report about *your* results.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, KeepTogether)

from . import __version__, config
from .papers import load_papers, parse_publish_date

log = logging.getLogger("btli.report")
TEAL, DARK, LIGHT = colors.HexColor("#1F7A8C"), colors.HexColor("#1B2A41"), colors.HexColor("#EAF3F5")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, textColor=DARK, spaceBefore=14, spaceAfter=8, keepWithNext=1)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=TEAL, spaceBefore=10, spaceAfter=4, keepWithNext=1)
BODY = ParagraphStyle("B", parent=ss["BodyText"], fontSize=10, leading=14, spaceAfter=6)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
CELL = ParagraphStyle("C", parent=BODY, fontSize=8.5, leading=10.5, spaceAfter=0)
CELLB = ParagraphStyle("CB", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
CAP = ParagraphStyle("Cap", parent=SMALL, alignment=TA_CENTER, spaceAfter=10)
NOTE = ParagraphStyle("Note", parent=BODY, backColor=colors.HexColor("#FFF4E5"), borderPadding=6,
                      borderColor=colors.HexColor("#E0A458"), borderWidth=0.6, leftIndent=6, rightIndent=6)


def P(t, st=BODY): return Paragraph(t, st)
def bullets(items): return [P("&bull; " + i, ParagraphStyle("bl", parent=BODY, leftIndent=14, firstLineIndent=-8, spaceAfter=3)) for i in items]


def table(data, widths=None, header=True, zebra=True):
    rows = [[Paragraph(escape(str(c)), CELLB if (header and r == 0) else CELL) for c in row]
            for r, row in enumerate(data)]
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), TEAL))
    if zebra:
        st += [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2, len(rows), 2)]
    t.setStyle(TableStyle(st))
    return t


def df_table(df, widths=None):
    return table([list(df.columns)] + df.astype(str).values.tolist(), widths)


def img(path, width_cm, caption=None):
    from PIL import Image as PILImage
    w, h = PILImage.open(path).size
    el = [Image(str(path), width=width_cm * cm, height=width_cm * cm * h / w)]
    if caption:
        el.append(P(escape(caption), CAP))
    return KeepTogether(el)


def architecture_png(path: Path):
    fig, ax = plt.subplots(figsize=(9, 2.6)); ax.axis("off"); ax.set_xlim(0, 100); ax.set_ylim(0, 30)
    boxes = [("INPUT_CSV.csv\n200 papers", 1, "#DDDDDD"), ("1 scrape.py\nrequests -> Playwright\nHTML + PDF", 21, "#BFE3EA"),
             ("2 extract.py\ntrafilatura / bs4 / pypdf\ntext + tables", 41, "#BFE3EA"),
             ("3 analyze.py\nTF-IDF, lexicons,\nvalidation", 61, "#BFE3EA"), ("4 report.py\nPDF + charts", 81, "#F4D8A8")]
    for label, x, c in boxes:
        ax.add_patch(plt.Rectangle((x, 8), 17.5, 15, fc=c, ec="#1B2A41", lw=1))
        ax.text(x + 8.75, 15.5, label, ha="center", va="center", fontsize=7.5)
    for x in (18.6, 38.6, 58.6, 78.6):
        ax.annotate("", xy=(x + 2.3, 15.5), xytext=(x, 15.5), arrowprops=dict(arrowstyle="->", lw=1.4))
    ax.text(50, 3, "manifests (scrape_manifest.csv, extraction_manifest.csv) connect the stages; "
            "papers.py + config.py are shared by all", ha="center", fontsize=7.5, style="italic")
    fig.savefig(path, dpi=200, bbox_inches="tight"); plt.close(fig)


FIXES = [
    ["Download", "16 of the 200 URLs are PDFs; they were saved through response.text as corrupt '.html'.",
     "Detect PDF by Content-Type / %PDF magic bytes; save as .pdf; extract with pypdf."],
    ["Download", "INPUT_CSV was defined twice ('csv_csv.csv' then 'INPUT_CSV.csv'); fragile order-dependent config.",
     "Single source of truth in config.py + --csv option."],
    ["Download", "A new Chromium instance was launched for every fallback page (slow, memory heavy).",
     "One lazily-started browser/context reused for the whole run and closed in a finally block."],
    ["Download", "Playwright waited only for 'networkidle' - analytics-heavy sites often never reach it and time out.",
     "Wait for domcontentloaded, then best-effort networkidle (10 s cap)."],
    ["Download", "No retry/back-off; a transient 429/503 became a permanent failure. 403/404 were also fetched twice.",
     "3 attempts with exponential back-off for 429/5xx/network errors; 4xx stops immediately."],
    ["Download", "response.text can mis-decode pages with no charset header (ISO-8859-1 default).",
     "Fall back to apparent_encoding when no charset is declared."],
    ["Download", "Only failures were logged, so coverage could not be computed; cached files lost their status.",
     "scrape_manifest.csv with status/method/kind/visible_chars for every row; resume-safe."],
    ["Naming", "{firm}_{date}_{first 8 title words} could collide; the 'already saved' check then skipped a real paper. "
               "Dates such as 'Q4 2025', '2025/2026', 'n.d.' were mis-parsed by dateutil fuzzy mode.",
     "6-char hash of firm+title+url added; explicit parser for quarter/range/no-date tokens; missing day/month never invented."],
    ["Extraction", "Folders had to be passed by hand (python extract_html.py folderA folderB ...) and the path layout "
                   "(extracted_text/<folder>/) only matched analysis by convention.",
     "Driven by the paper list and the shared Paper.stem; no manual folder arguments."],
    ["Extraction", "The BeautifulSoup fallback existed only as a comment.",
     "Implemented: used when trafilatura gives nothing or fewer than 150 words and bs4 finds more."],
    ["Extraction", "Malformed XML from trafilatura would crash the whole run.",
     "ParseError handled per page; error recorded in extraction_manifest.csv."],
    ["Analysis", "analyze_themes.py imported scrape_whitepapers just for build_output_path, pulling in requests/bs4 "
                 "and breaking if Playwright config changed.",
     "Shared papers.py; each stage can be run and tested alone."],
    ["Analysis", "Lexicon keys ('AI & Agentic', ...) did not match the CSV categories, so lexicons could not be validated.",
     "Keys now equal Trend_category; new lexicon_validation step reports agreement with human labels."],
    ["Analysis", "Overlapping terms were double-counted ('generative ai' and 'ai' both hit).",
     "Single longest-first alternation regex per theme."],
    ["Analysis", "TF-IDF with max_df=1.0 and publisher names left in the text let site boilerplate and firm names "
                 "dominate 'distinctive' terms.",
     "max_df=0.75 (term must be absent from at least one firm) and a boilerplate stop-list."],
    ["Analysis", "Only 3 outputs (stats, terms, density).",
     "Added readability (Flesch), category coverage, firm similarity, lexicon validation and 5 charts."],
]


def _read(path, **kw):
    return pd.read_csv(path, **kw) if Path(path).exists() else None


def build(settings: config.Settings, run_label: str = "") -> Path:
    settings.ensure()
    a = settings.analysis_dir
    arch = a / "architecture.png"
    architecture_png(arch)
    papers = load_papers(settings.csv_path)
    df = pd.DataFrame([p.__dict__ for p in papers])
    domains = df["url"].str.extract(r"https?://([^/]+)")[0]
    synthetic = run_label.lower().startswith("synthetic")

    doc = SimpleDocTemplate(str(settings.report_pdf), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title="BTLI Project Report",
                            author="BTLI pipeline")
    W = A4[0] - 4 * cm
    S = []

    # ---- title -----------------------------------------------------------
    S += [Spacer(1, 4 * cm), P("Big 4 Thought-Leadership Intelligence", ParagraphStyle("T", parent=H1, fontSize=26, textColor=DARK)),
          P("Project Report", ParagraphStyle("T2", parent=H1, fontSize=18, textColor=TEAL)), Spacer(1, 0.6 * cm),
          P("An end-to-end Python pipeline that collects, cleans and analyses the published thought leadership of "
            "Deloitte, EY, KPMG and PwC to show what each firm emphasises."),
          Spacer(1, 1 * cm),
          table([["Version", __version__], ["Generated", dt.date.today().isoformat()],
                 ["Input", f"{settings.csv_path.name} ({len(papers)} papers)"],
                 ["Results basis", run_label or "not specified"]], [4 * cm, 12 * cm], header=False)]
    if synthetic:
        S += [Spacer(1, 0.6 * cm),
              P("<b>Important:</b> the result tables and charts in this edition come from a <b>synthetic</b> corpus "
                "generated offline (random sentences built from the theme lexicons plus invented marker words). "
                "They demonstrate that the pipeline works and can recover planted signals; they say "
                "<b>nothing</b> about what Deloitte, EY, KPMG or PwC actually publish. Run "
                "<font face='Courier'>python -m btli all</font> on a networked machine to regenerate this report from real pages.", NOTE)]
    S.append(PageBreak())

    # ---- 1 summary ---------------------------------------------------------
    S += [P("1. Executive summary", H1),
          P("The original work consisted of three separate scripts (download, extract, analyse) that depended on each other "
            "through file-name conventions and an import between the first and last script. This project restructures them into one "
            "installable package with a command-line interface, shared configuration, run manifests, automated tests and an "
            "automatically generated report. During the restructuring 16 defects or weaknesses were fixed (Section 6); the most "
            f"important is that {int(df['url'].str.lower().str.endswith('.pdf').sum())} of the {len(df)} source URLs are PDF files, "
            "which the original downloader would have saved as corrupted HTML.")]
    S += bullets(["<b>Stage 1 - scrape:</b> requests first, headless Chromium (Playwright) only for pages that look empty; HTML and PDF handled.",
                  "<b>Stage 2 - extract:</b> trafilatura for article text and tables, BeautifulSoup and pypdf as fallbacks; pages under 150 words flagged.",
                  "<b>Stage 3 - analyze:</b> TF-IDF distinctive terms, five keyword-lexicon themes per 1,000 words, readability, firm similarity, and a validation of the lexicons against the human category labels.",
                  "<b>Stage 4 - report:</b> this PDF, rebuilt from the data every run."])

    # ---- 2 objectives ------------------------------------------------------
    S += [P("2. Problem statement and objectives", H1),
          P("Professional-services firms use published research to shape client agendas. Comparing four firms by hand across "
            "five topics and 200 documents is slow and subjective. The objectives are to (1) build a reproducible corpus from a curated URL list, "
            "(2) quantify which themes each firm stresses, (3) surface vocabulary that is distinctive to each firm, "
            "(4) describe how large and readable each firm's corpus is, and (5) make every step transparent enough to audit.")]

    # ---- 3 data ------------------------------------------------------------
    S += [P("3. Input data", H1),
          P(f"The input file lists {len(df)} papers with the columns Firm, Title, Url, Publish_date and Trend_category. "
            "The table shows the papers per firm and category as given in the CSV (before any download).")]
    ct = pd.crosstab(df["firm"], df["category"])[list(config.LEXICONS)] if set(df["category"]) <= set(config.LEXICONS) else pd.crosstab(df["firm"], df["category"])
    ct["Total"] = ct.sum(axis=1)
    ct = ct.reset_index().rename(columns={c: config.SHORT_LABELS.get(c, c) for c in ct.columns})
    S += [df_table(ct), Spacer(1, 6)]
    nodate = sum(parse_publish_date(d) == "nodate" for d in df["publish_date"])
    dom = domains.value_counts().head(8)
    S += [P("Data-quality observations computed from the CSV:", H2)]
    S += bullets([f"{int(df['url'].str.lower().str.endswith('.pdf').sum())} URLs end in .pdf; {int(df['url'].duplicated().sum())} URL appears twice (different titles).",
                  f"{nodate} rows have no usable date ('n.d.', 'Not specified', 'Rolling/current'); the rest use at least 8 different date formats.",
                  "Hosts: " + ", ".join(f"{h} ({n})" for h, n in dom.items()) + "."])

    # ---- 4 architecture ----------------------------------------------------
    S += [P("4. System design", H1), img(arch, 16.5, "Figure 1 - pipeline architecture"),
          table([["Module", "Responsibility", "Replaces"],
                 ["btli/config.py", "Paths, thresholds, theme lexicons, stop-lists", "constants scattered in 3 scripts"],
                 ["btli/papers.py", "CSV loading, date parsing, unique file stems", "build_output_path in scrape_whitepapers.py"],
                 ["btli/scrape.py", "Download HTML/PDF with retries and browser fallback", "scrape_whitepapers.py"],
                 ["btli/extract.py", "Text, tables, PDF text, fallbacks, flags", "extract_html.py"],
                 ["btli/analyze.py", "Statistics, TF-IDF, theme density, validation, charts", "analyze_themes.py"],
                 ["btli/report.py", "PDF report generation", "(new)"],
                 ["btli/demo.py", "Synthetic offline corpus for demos and tests", "(new)"],
                 ["btli/__main__.py", "CLI: scrape | extract | analyze | report | all | demo", "(new)"]],
                [3.6 * cm, 8.4 * cm, 4.5 * cm])]

    # ---- 5 method ----------------------------------------------------------
    S += [P("5. Methodology", H1), P("5.1 Collection", H2),
          P(f"Each URL is requested with a browser-like User-Agent. A page whose visible text is under {config.MIN_TEXT_CHARS} characters is "
            "treated as a JavaScript shell and re-fetched with Chromium. A random 2-3 s pause separates rows so the sites are not "
            "hammered. Files are cached, so a stopped run can be resumed. Rows that fail or stay thin are listed in failed_saves.csv."),
          P("5.2 Extraction", H2),
          P(f"trafilatura scores page blocks and keeps article content, dropping menus, footers and cookie banners. Tables are taken from its XML "
            f"output and written as CSV. If the result has fewer than {config.MIN_WORDS} words a BeautifulSoup extraction is tried and the longer text is kept. "
            "PDFs are read with pypdf. Papers under the word threshold are flagged and excluded from the analysis."),
          P("5.3 Analysis", H2)]
    S += bullets(["<b>Corpus statistics:</b> papers, words, mean sentence length and Flesch reading ease per firm (syllables estimated from vowel groups).",
                  "<b>Distinctive terms:</b> all of a firm's papers are joined into one document; uni- and bi-gram TF-IDF (sublinear tf) is computed across the four firm documents. Terms present in all four firms and publisher/site words are excluded.",
                  "<b>Theme emphasis:</b> five lexicons, one per CSV category. Whole-word, case-insensitive matching with longest-term-first so there is no double counting. Reported as hits per 1,000 words.",
                  "<b>Lexicon validation:</b> per paper the five densities are z-scored across the corpus and the highest is compared with the human Trend_category. Agreement is a sanity check of the lexicons, not a claim about the firms.",
                  "<b>Firm similarity:</b> cosine similarity between the four firm-level TF-IDF vectors."])

    # ---- 6 fixes -----------------------------------------------------------
    S += [P("6. Defects found in the original scripts and how they were fixed", H1),
          table([["Area", "Problem", "Fix in this project"]] + FIXES, [2.2 * cm, 7.4 * cm, 6.9 * cm])]

    # ---- 7 results ---------------------------------------------------------
    S += [PageBreak(), P("7. Results", H1), P(f"<b>Results basis:</b> {escape(run_label)}", NOTE if synthetic else BODY)]
    sm = _read(settings.scrape_manifest, encoding="utf-8-sig")
    em = _read(settings.extract_manifest, encoding="utf-8-sig")
    if sm is not None:
        S += [P("7.1 Collection coverage", H2), df_table(sm["status"].value_counts().rename_axis("download status").reset_index(name="papers"), [6 * cm, 3 * cm])]
    if em is not None:
        em = em.fillna("")
        usable = int(((em["words"].astype(float) >= settings.min_words)).sum())
        S += [Spacer(1, 6), P(f"Of {len(em)} papers, <b>{usable}</b> have at least {settings.min_words} words of extracted text and enter the analysis; "
                              f"{int((em['flag'] != '').sum())} are flagged for manual review (see extraction_manifest.csv).")]
    stats = _read(a / "corpus_stats.csv")
    if stats is None:
        S += [P("No analysis output found yet - run the analyze stage and rebuild the report.", NOTE)]
    else:
        S += [P("7.2 Corpus size and readability", H2), df_table(stats), Spacer(1, 4), img(a / "corpus_size.png", 9, "Figure 2 - words analysed per firm")]
        S += [P("7.3 Theme emphasis", H2),
              P("Each cell is the number of lexicon hits per 1,000 words in a firm's usable papers. Compare across a row to see which theme a firm leans towards; "
                "compare down a column to see who stresses a theme most."),
              img(a / "theme_density_heatmap.png", 15, "Figure 3 - theme emphasis by firm")]
        dens = _read(a / "theme_density.csv")
        if dens is not None:
            top = dens.loc[dens.groupby("firm")["per_1000_words"].idxmax()][["firm", "theme", "per_1000_words"]]
            S += [P("Highest-density theme per firm: " + "; ".join(f"<b>{escape(r.firm)}</b> - {escape(config.SHORT_LABELS.get(r.theme, r.theme))} ({r.per_1000_words})" for r in top.itertuples()) + ".")]
        S += [P("7.4 Distinctive vocabulary", H2), img(a / "distinctive_terms.png", 16.5, "Figure 4 - top TF-IDF terms per firm")]
        terms = _read(a / "distinctive_terms.csv")
        if terms is not None:
            pv = terms[terms["rank"] <= 5].groupby("firm")["term"].apply(", ".join).reset_index()
            S += [df_table(pv.rename(columns={"term": "top 5 distinctive terms"}), [3 * cm, 13.5 * cm])]
            if synthetic:
                from .demo import SIGNATURES
                rows = [["Firm", "Planted marker words", "Found in top 15", "Recovered"]]
                for firm, sig in SIGNATURES.items():
                    got = [t for t in terms[terms.firm == firm]["term"] if t in sig]
                    rows.append([firm, len(sig), len(got), f"{100*len(got)/len(sig):.0f}%"])
                S += [Spacer(1, 6), P("<b>Planted-signal recovery test</b> (synthetic run only): invented marker words were inserted into each firm's texts; a working TF-IDF step must rank them for the right firm.", BODY),
                      table(rows, [3 * cm, 4.5 * cm, 4.5 * cm, 4 * cm])]
        sim = _read(a / "firm_similarity.csv", index_col=0)
        if sim is not None:
            S += [P("7.5 Firm similarity", H2), img(a / "firm_similarity.png", 8.5, "Figure 5 - cosine similarity of firm corpora")]
        val = _read(a / "lexicon_validation.csv")
        if val is not None:
            acc = 100 * val["correct"].mean()
            S += [P("7.6 Lexicon validation", H2),
                  P(f"Across {len(val)} usable papers the lexicon-based prediction matches the human category label for <b>{acc:.1f}%</b> of papers "
                    f"(random guessing among five classes would give about 20%)."),
                  img(a / "lexicon_validation.png", 11, "Figure 6 - agreement by category")]

    # ---- 8 testing ---------------------------------------------------------
    tests_dir = settings.csv_path.resolve().parents[1] / "tests"
    n_tests = sum(len(re.findall(r"^def test_", f.read_text(), re.M)) for f in tests_dir.glob("test_*.py")) if tests_dir.exists() else 0
    S += [P("8. Testing", H1),
          P(f"The tests/ folder holds {n_tests} automated pytest tests. They cover date parsing for every format found in the CSV, unique file names for all 200 rows, "
            "the no-double-counting rule of the lexicon matcher, HTML/table/PDF extraction, thin-page flagging, and a full offline pipeline run "
            "(generate synthetic corpus, extract, analyse, build PDF) including the planted-signal recovery check. Run them with <font face='Courier'>pytest -q</font>. "
            "Network behaviour (live downloading) cannot be unit-tested deterministically and must be checked by running stage 1 on a small sample "
            "(<font face='Courier'>python -m btli scrape --limit 5</font>).")]

    # ---- 9 limits ----------------------------------------------------------
    S += [P("9. Limitations and responsible use", H1)]
    S += bullets(["<b>Only four documents enter TF-IDF</b> (one per firm). It highlights vocabulary, but small differences are not statistically tested.",
                  "<b>Keyword lexicons are a proxy</b> for topics: they miss paraphrase and can count a word used in another sense ('deal with'). The validation step quantifies this but does not remove it.",
                  "<b>Selection bias:</b> the 200 URLs were curated (50 per firm, 40 per category), so results describe that sample, not each firm's entire output. Landing pages and press releases are mixed with full reports.",
                  "<b>Balanced design:</b> 10 papers per firm and category means theme densities mostly measure how heavily each firm uses a topic's vocabulary, not how often it chooses to write on the topic.",
                  "<b>Dates are descriptive only:</b> about one-fifth of rows have no usable date, so no time-trend analysis is made.",
                  "<b>Access:</b> some sites block automated clients, require JavaScript, or sit behind consent walls; those pages appear in failed_saves.csv. Check each site's terms of use and robots.txt before running at scale, keep the 2-3 s delay, and do not redistribute the downloaded content.",
                  "<b>Language:</b> English-only stop-words, readability formula and lexicons; non-English pages will be mis-measured."])

    # ---- 10 run ------------------------------------------------------------
    S += [P("10. Environment and how to run", H1),
          table([["Item", "Value"], ["Python", "3.10 - 3.12"],
                 ["Libraries", "requests, beautifulsoup4, lxml, trafilatura, pypdf, python-dateutil, pandas, numpy, scikit-learn, matplotlib, reportlab, pillow, playwright, pytest"],
                 ["Browser", "Chromium via 'playwright install chromium' (only used as fallback)"],
                 ["Install (pip)", "python -m venv .venv; activate; pip install -r requirements.txt; playwright install chromium"],
                 ["Install (conda)", "conda env create -f environment.yml; conda activate btli; playwright install chromium"],
                 ["Full run", "python -m btli all   (expect roughly 10-30 min: 200 rows x 2-3 s delay plus download time)"],
                 ["Offline demo", "python -m btli demo   (synthetic data, runs in seconds)"],
                 ["Single stages", "python -m btli scrape | extract | analyze | report   [--limit N] [--no-playwright] [--workdir DIR]"],
                 ["Docker", "docker build -t btli . && docker run --rm -v $PWD/output:/app/output btli"]],
                [3.4 * cm, 13.1 * cm])]

    # ---- 11 future ---------------------------------------------------------
    S += [P("11. Future work", H1)]
    S += bullets(["Replace keyword lexicons with embedding- or LLM-based topic classification and compare with the human labels.",
                  "Paper-level (not firm-level) TF-IDF or BERTopic to find sub-themes inside each category.",
                  "Add sentiment / hedging language analysis and a time-trend view once dates are researched manually.",
                  "Respect robots.txt automatically and add conditional GET (ETag) so re-runs only fetch changed pages.",
                  "Interactive dashboard (Streamlit) on top of the analysis CSVs."])

    def footer(canvas, d):
        canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, "BTLI - Big 4 Thought-Leadership Intelligence")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {d.page}"); canvas.restoreState()

    doc.build(S, onFirstPage=lambda c, d: None, onLaterPages=footer)
    log.info("Report written -> %s", settings.report_pdf)
    return settings.report_pdf
