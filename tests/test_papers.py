import pytest
from btli.config import ROOT
from btli.papers import load_papers, parse_publish_date, sanitize, Paper

CASES = {
    "06/23/2026": "2026-06-23", "Jan 29, 2026": "2026-01-29", "Jun 23, 2026": "2026-06-23",
    "Jan 2026": "2026-01", "Sept 2025": "2025-09", "Q4 2025": "2025-Q4", "2025/2026": "2025-2026",
    "2026": "2026", "n.d.": "nodate", "Not specified": "nodate", "Rolling/current": "nodate",
    "": "nodate", None: "nodate",
}


@pytest.mark.parametrize("raw,expected", CASES.items())
def test_parse_publish_date(raw, expected):
    assert parse_publish_date(raw) == expected


def test_sanitize_removes_unsafe_chars():
    assert sanitize('A/B: "C"?*') == "AB-C"
    assert sanitize("") == "untitled"


def test_real_csv_loads_and_stems_are_unique():
    papers = load_papers(ROOT / "data" / "INPUT_CSV.csv")
    assert len(papers) == 200
    assert len({p.stem for p in papers}) == 200          # no collisions
    assert {p.firm for p in papers} == {"Deloitte", "EY", "KPMG", "PWC"}


def test_same_title_same_date_different_url_do_not_collide():
    a = Paper(1, "EY", "Same long title for both papers in the list here", "http://a", "2026", "x")
    b = Paper(2, "EY", "Same long title for both papers in the list here", "http://b", "2026", "x")
    assert a.stem != b.stem


def test_missing_column_raises(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("Firm,Title\nEY,x\n")
    with pytest.raises(ValueError):
        load_papers(f)


def test_header_with_stray_space_is_accepted(tmp_path):
    f = tmp_path / "ok.csv"
    f.write_text("Firm,Title,Url, Publish_date,Trend_category\nEY,T,http://x,2026,C\n", encoding="utf-8")
    assert load_papers(f)[0].publish_date == "2026"
