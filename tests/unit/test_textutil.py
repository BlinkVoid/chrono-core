from __future__ import annotations

from chrono_core.textutil import (
    phrase_project_counts,
    salient_terms,
    term_project_counts,
    tokenize,
)


def test_tokenize_lowercases_drops_stopwords_and_short_tokens():
    tokens = tokenize("The Retry Loop retries retries flaky DB calls")
    assert "retries" in tokens
    assert "flaky" in tokens
    assert "the" not in tokens
    assert "db" not in tokens  # too short (min 3 chars)
    assert tokens == [t.lower() for t in tokens]


def test_salient_terms_rank_by_frequency_then_term():
    terms = salient_terms("alpha beta alpha gamma beta alpha", limit=2)
    assert terms == ["alpha", "beta"]


def test_term_project_counts_counts_distinct_projects():
    docs = [
        ("p1", "circuit breaker circuit"),
        ("p2", "circuit breaker"),
        ("p3", "breaker breaker breaker"),
    ]
    counts = term_project_counts(docs)
    assert counts["circuit"] == {"p1": 2, "p2": 1}
    assert counts["breaker"]["p3"] == 3
    assert set(counts["breaker"]) == {"p1", "p2", "p3"}


def test_phrase_project_counts_excludes_single_words():
    counts = phrase_project_counts(
        [("p1", "circuit breaker circuit"), ("p2", "circuit breaker")]
    )

    assert counts["circuit breaker"] == {"p1": 1, "p2": 1}
    assert "circuit" not in counts
