import pandas as pd
from btli import analyze, config, demo, extract, report
from btli.extract import extract_html, tables_from_xml

LONG = " ".join(["Organisations expect rapid change and plan investment in new capability."] * 30)
PAGE = f"""<html><body><nav>Home Cookie settings</nav><article><h1>T</h1><p>{LONG}</p>
<table><tr><th>Metric</th><th>Value</th></tr><tr><td>Respondents</td><td>500</td></tr></table>
</article><footer>Copyright All rights reserved</footer></body></html>"""


def test_extract_html_keeps_body_and_finds_table():
    text, tables, method = extract_html(PAGE.encode())
    assert "Organisations expect rapid change" in text
    assert "Cookie settings" not in text
    assert tables and tables[0][1] == ["Respondents", "500"]


def test_tables_from_bad_xml_is_empty():
    assert tables_from_xml("<not-xml") == []


def test_theme_counter_no_double_counting_and_whole_words():
    t = "generative ai is great. ai said maintain. m&a and carve-out deals."
    assert analyze.count_theme_hits(t, "Enterprise / Agentic AI Adoption") == 2   # 'generative ai' + 'ai'
    assert analyze.count_theme_hits(t, "M&A and Deal Activity") == 3              # m&a, carve-out, deals


def test_flesch_is_finite_for_normal_text():
    assert -50 < analyze.flesch_reading_ease("The cat sat on the mat. It was happy.") < 130


def test_full_offline_pipeline(tmp_path):
    s = config.Settings(workdir=tmp_path, delay=(0, 0))
    n = demo.generate(s, seed=3)
    assert n == 200
    assert list((s.raw_dir).rglob("*.pdf")), "PDF rows must be written as .pdf"
    rows = extract.run(s)
    assert any(r["method"] == "pypdf" and r["words"] > 150 for r in rows)      # PDF path works
    flagged = [r for r in rows if r["flag"].startswith("short") or r["flag"] == "no_text"]
    assert flagged, "JS-shell pages must be flagged"
    res = analyze.run(s)
    assert res and res["n_papers"] > 150
    # planted signal recovery: every firm's top terms contain at least half its markers
    terms = res["terms"]
    for firm, sig in demo.SIGNATURES.items():
        got = set(terms[terms.firm == firm]["term"]) & set(sig)
        assert len(got) >= len(sig) // 2, (firm, got)
    # lexicon beats random (20%) by a wide margin
    assert res["validation"]["correct"].mean() > 0.5
    pdf = report.build(s, run_label="Synthetic test run")
    assert pdf.exists() and pdf.stat().st_size > 20_000


def test_analyze_requires_extraction(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        analyze.run(config.Settings(workdir=tmp_path))
