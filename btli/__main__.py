"""Command line interface:  python -m btli <command> [options]"""
from __future__ import annotations

import argparse
import logging
import sys

from . import analyze, config, demo, extract, report, scrape


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="btli", description="Big 4 Thought-Leadership Intelligence pipeline")
    ap.add_argument("command", choices=["scrape", "extract", "analyze", "report", "all", "demo"],
                    help="stage to run ('all' = scrape+extract+analyze+report, "
                         "'demo' = offline run on SYNTHETIC data)")
    ap.add_argument("--csv", default=str(config.ROOT / "data" / "INPUT_CSV.csv"), help="input CSV")
    ap.add_argument("--workdir", default=None, help="output folder (default: ./output, ./output_demo for demo)")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N rows (for testing)")
    ap.add_argument("--no-playwright", action="store_true", help="never start the headless browser")
    ap.add_argument("--min-words", type=int, default=config.MIN_WORDS)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    workdir = a.workdir or str(config.ROOT / ("output_demo" if a.command == "demo" else "output"))
    s = config.Settings(csv_path=a.csv, workdir=workdir, min_words=a.min_words,
                        use_playwright=not a.no_playwright)

    if a.command == "demo":
        n = demo.generate(s, limit=a.limit)
        logging.info("Generated %d SYNTHETIC raw files in %s", n, s.raw_dir)
        extract.run(s, limit=a.limit)
        analyze.run(s)
        report.build(s, run_label="Synthetic demo corpus (offline validation - not real firm content)")
        return 0
    if a.command in ("scrape", "all"):
        scrape.run(s, limit=a.limit)
    if a.command in ("extract", "all"):
        extract.run(s, limit=a.limit)
    if a.command in ("analyze", "all"):
        if analyze.run(s) is None:
            return 1
    if a.command in ("report", "all"):
        report.build(s, run_label="Live corpus downloaded from the URLs in the input CSV")
    return 0


if __name__ == "__main__":
    sys.exit(main())
