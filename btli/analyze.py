"""Stage 3 - text analytics.

Outputs (all in ``<workdir>/analysis``):
  corpus_stats.csv         papers, words, sentence length, Flesch reading ease per firm
  category_coverage.csv    usable papers / words per firm x category
  distinctive_terms.csv    TF-IDF terms that characterise each firm
  firm_similarity.csv      cosine similarity between firms' whole corpora
  theme_density.csv        lexicon hits per 1,000 words, firm x theme
  lexicon_validation.csv   does the lexicon agree with the human category label?
  *.png                    charts
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config

log = logging.getLogger("btli.analyze")

_THEME_RX = {}


def _theme_regex(theme: str):
    """One alternation per theme, longest term first, so that
    'generative ai' is one hit - not also a second hit for 'ai'."""
    if theme not in _THEME_RX:
        terms = sorted(config.LEXICONS[theme], key=len, reverse=True)
        body = "|".join(re.escape(t) for t in terms)
        _THEME_RX[theme] = re.compile(r"(?<![\w&])(?:" + body + r")(?![\w&])")
    return _THEME_RX[theme]


def count_theme_hits(text_lower: str, theme: str) -> int:
    return len(_theme_regex(theme).findall(text_lower))


def count_syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and n > 1 and not word.endswith("le"):
        n -= 1
    return max(1, n)


def flesch_reading_ease(text: str) -> float:
    words = re.findall(r"[A-Za-z']+", text)
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    if not words:
        return float("nan")
    syll = sum(count_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syll / len(words))


def load_corpus(settings: config.Settings) -> pd.DataFrame:
    """Usable papers = extracted text with at least ``min_words`` words."""
    if not settings.extract_manifest.exists():
        raise FileNotFoundError("Run the extract stage first (extraction_manifest.csv missing).")
    man = pd.read_csv(settings.extract_manifest, encoding="utf-8-sig").fillna("")
    rows = []
    for r in man.itertuples():
        if not r.text_path or int(r.words) < settings.min_words:
            continue
        text = open(r.text_path, encoding="utf-8", errors="ignore").read()
        sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
        rows.append({"firm": r.firm, "title": r.title, "category": r.trend_category, "text": text,
                     "words": len(text.split()), "avg_sentence_len": len(text.split()) / sentences,
                     "flesch": flesch_reading_ease(text)})
    return pd.DataFrame(rows)


def corpus_stats(df: pd.DataFrame) -> pd.DataFrame:
    return (df.groupby("firm")
              .agg(papers=("title", "count"), total_words=("words", "sum"), avg_words=("words", "mean"),
                   avg_sentence_len=("avg_sentence_len", "mean"), flesch_reading_ease=("flesch", "mean"))
              .round(1).reset_index())


def distinctive_terms(df: pd.DataFrame, top_n: int = config.TOP_N_TERMS) -> pd.DataFrame:
    """Firm-level TF-IDF.  A term must be absent from at least one firm
    (max_df=0.75) so generic words shared by everybody cannot win."""
    firm_docs = df.groupby("firm")["text"].apply(" ".join)
    stop = list(ENGLISH_STOP_WORDS | config.BOILERPLATE_WORDS)
    vec = TfidfVectorizer(stop_words=stop, ngram_range=(1, 2), min_df=1, max_df=0.75,
                          token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b", sublinear_tf=True)
    mat = vec.fit_transform(firm_docs.values)
    vocab = vec.get_feature_names_out()
    out = []
    for i, firm in enumerate(firm_docs.index):
        scores = mat[i].toarray().ravel()
        for rank, j in enumerate(scores.argsort()[::-1][:top_n], start=1):
            out.append({"firm": firm, "rank": rank, "term": vocab[j], "tfidf": round(float(scores[j]), 4)})
    return pd.DataFrame(out)


def firm_similarity(df: pd.DataFrame) -> pd.DataFrame:
    firm_docs = df.groupby("firm")["text"].apply(" ".join)
    stop = list(ENGLISH_STOP_WORDS | config.BOILERPLATE_WORDS)
    vec = TfidfVectorizer(stop_words=stop, sublinear_tf=True, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b")
    sim = cosine_similarity(vec.fit_transform(firm_docs.values))
    return pd.DataFrame(sim, index=firm_docs.index, columns=firm_docs.index).round(3)


def theme_density(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for firm, g in df.groupby("firm"):
        lower = " ".join(g["text"]).lower()
        total = len(lower.split())
        for theme in config.LEXICONS:
            hits = count_theme_hits(lower, theme)
            out.append({"firm": firm, "theme": theme, "hits": hits,
                        "per_1000_words": round(1000 * hits / total, 2)})
    return pd.DataFrame(out)


def lexicon_validation(df: pd.DataFrame) -> pd.DataFrame:
    """Sanity-check the lexicons against the human 'Trend_category' labels.

    Per paper we compute density for every theme, z-score each theme across
    the corpus (so big lexicons do not dominate), predict the highest, and
    compare with the labelled category.
    """
    themes = list(config.LEXICONS)
    dens = np.array([[1000 * count_theme_hits(t.lower(), th) / max(1, len(t.split())) for th in themes]
                     for t in df["text"]])
    z = (dens - dens.mean(0)) / np.where(dens.std(0) == 0, 1, dens.std(0))
    pred = [themes[i] for i in z.argmax(1)]
    res = pd.DataFrame({"firm": df["firm"], "title": df["title"], "label": df["category"], "predicted": pred})
    res["correct"] = res["label"] == res["predicted"]
    return res


# ----------------------------------------------------------------------------
def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def charts(settings, stats, terms, sim, dens, val):
    d = settings.analysis_dir
    pivot = dens.pivot(index="firm", columns="theme", values="per_1000_words")[list(config.LEXICONS)]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    im = ax.imshow(pivot.values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(pivot.shape[1]), [config.SHORT_LABELS[c] for c in pivot.columns], rotation=25, ha="right")
    ax.set_yticks(range(pivot.shape[0]), pivot.index)
    for r in range(pivot.shape[0]):
        for c in range(pivot.shape[1]):
            v = pivot.values[r, c]
            ax.text(c, r, f"{v:.1f}", ha="center", va="center", fontsize=9,
                    color="white" if v > (pivot.values.min() + pivot.values.max()) / 2 else "black")
    ax.set_title("Theme emphasis by firm (lexicon hits per 1,000 words)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    _save(fig, d / "theme_density_heatmap.png")

    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.bar(stats["firm"], stats["total_words"], color="#1F7A8C")
    ax.set_ylabel("Words analysed"); ax.set_title("Corpus size by firm")
    _save(fig, d / "corpus_size.png")

    fig, ax = plt.subplots(figsize=(4.8, 3.8))
    im = ax.imshow(sim.values, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(sim)), sim.columns); ax.set_yticks(range(len(sim)), sim.index)
    for r in range(len(sim)):
        for c in range(len(sim)):
            ax.text(c, r, f"{sim.values[r, c]:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if sim.values[r, c] > 0.6 else "black")
    ax.set_title("Firm-to-firm content similarity (cosine)")
    fig.colorbar(im, ax=ax, shrink=0.8)
    _save(fig, d / "firm_similarity.png")

    firms = list(terms["firm"].unique())
    fig, axes = plt.subplots(1, len(firms), figsize=(3.2 * len(firms), 4), sharex=False)
    for ax, firm in zip(np.atleast_1d(axes), firms):
        t = terms[terms.firm == firm].head(8).iloc[::-1]
        ax.barh(t["term"], t["tfidf"], color="#1F7A8C")
        ax.set_title(firm, fontsize=10); ax.tick_params(labelsize=7)
    fig.suptitle("Most distinctive terms per firm (TF-IDF)", fontsize=11)
    _save(fig, d / "distinctive_terms.png")

    acc = val.groupby("label")["correct"].mean().reindex(list(config.LEXICONS)).fillna(0)
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    ax.bar([config.SHORT_LABELS[c] for c in acc.index], acc.values * 100, color="#E07A5F")
    ax.set_ylim(0, 100); ax.set_ylabel("Agreement with label (%)")
    ax.set_title("Lexicon vs human category label"); plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, d / "lexicon_validation.png")


def run(settings: config.Settings) -> Optional[dict]:
    df = load_corpus(settings)
    if df.empty:
        log.error("No usable text (>= %d words). Run scrape + extract first.", settings.min_words)
        return None
    settings.ensure()
    d = settings.analysis_dir
    log.info("Analysing %d papers from %d firms", len(df), df["firm"].nunique())

    stats = corpus_stats(df);               stats.to_csv(d / "corpus_stats.csv", index=False)
    cov = (df.groupby(["firm", "category"]).agg(papers=("title", "count"), words=("words", "sum"))
             .reset_index());               cov.to_csv(d / "category_coverage.csv", index=False)
    terms = distinctive_terms(df);          terms.to_csv(d / "distinctive_terms.csv", index=False)
    sim = firm_similarity(df);              sim.to_csv(d / "firm_similarity.csv")
    dens = theme_density(df);               dens.to_csv(d / "theme_density.csv", index=False)
    val = lexicon_validation(df);           val.to_csv(d / "lexicon_validation.csv", index=False)
    charts(settings, stats, terms, sim, dens, val)
    log.info("Lexicon/label agreement: %.1f%%", 100 * val["correct"].mean())
    return {"stats": stats, "coverage": cov, "terms": terms, "similarity": sim,
            "density": dens, "validation": val, "n_papers": len(df)}
