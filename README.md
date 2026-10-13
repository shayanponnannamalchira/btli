# BTLI - Big 4 Thought-Leadership Intelligence

Collects the thought-leadership papers listed in `data/INPUT_CSV.csv` (200 URLs: Deloitte, EY, KPMG, PwC x 5 topics),
cleans them, compares what each firm emphasises, and writes a PDF report.

```
INPUT_CSV.csv -> scrape (HTML+PDF) -> extract (text+tables) -> analyze (TF-IDF, themes) -> report (PDF)
```

## 1. Set up the environment (once)

**pip / venv**
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # only needed for JavaScript-heavy pages
```
**conda**
```bash
conda env create -f environment.yml && conda activate btli && playwright install chromium
```
**Docker**
```bash
docker build -t btli .
docker run --rm -v "$PWD/output:/app/output" btli          # full run
```

## 2. Run

| Command | What it does |
|---|---|
| `python -m btli demo` | Offline run on **synthetic** data (seconds). Output in `output_demo/`. Use it to check your setup. |
| `python -m btli scrape --limit 5` | Smoke-test the downloader on the first 5 rows. |
| `python -m btli all` | Full real run: scrape + extract + analyze + report. Needs internet; ~10-30 min. |
| `python -m btli scrape` / `extract` / `analyze` / `report` | Run a single stage (each reads the previous stage's files). |
| `pytest` | 25 automated tests. |

Options: `--csv PATH`, `--workdir DIR`, `--limit N`, `--no-playwright`, `--min-words N`, `-v`.
The downloader is resumable: stop it and run it again, finished files are skipped.

## 3. Where things end up (`output/`)

```
raw/<Firm>/<stem>.html|.pdf        downloaded pages
extracted_text/<Firm>/<stem>.txt   cleaned text
extracted_tables/<Firm>/<stem>_tableN.csv
scrape_manifest.csv                one line per paper: status, method, kind, chars
failed_saves.csv                   papers that failed or came back empty -> check by hand
extraction_manifest.csv            words, tables, flags per paper
analysis/                          corpus_stats, distinctive_terms, theme_density, firm_similarity,
                                   category_coverage, lexicon_validation (.csv) + charts (.png)
BTLI_Project_Report.pdf            the report, built from the files above
```

## 4. Customise
* Thresholds, delays, lexicons and stop-words: `btli/config.py`. Lexicon keys must equal the CSV `Trend_category` values.
* Input CSV needs the columns `Firm, Title, Url, Publish_date, Trend_category` (stray spaces in headers are tolerated).

## 5. Responsible use
Check each site's terms of use / robots.txt, keep the 2-3 s delay, and do not redistribute downloaded content.
Pages that block bots or need a login will show up in `failed_saves.csv`; fetch those manually.

## Project layout
```
btli/config.py   settings + lexicons      btli/scrape.py   stage 1      btli/analyze.py  stage 3
btli/papers.py   CSV, dates, file names   btli/extract.py  stage 2      btli/report.py   stage 4
btli/demo.py     synthetic test corpus    btli/__main__.py CLI
tests/           pytest suite             data/INPUT_CSV.csv
```
