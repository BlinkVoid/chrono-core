"""Shared deterministic text tokenizing used by pattern mining and scoring."""
from __future__ import annotations

import re

# Small curated English stopword list plus Chrono-domain filler words.
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "when",
        "then", "than", "are", "was", "were", "been", "have", "has", "had",
        "not", "but", "all", "any", "can", "will", "would", "should", "could",
        "our", "their", "its", "each", "which", "who", "whom", "out", "use",
        "used", "using", "new", "one", "two", "also", "may", "might", "per",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens of length >= 3 with stopwords removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def salient_terms(text: str, limit: int = 12) -> list[str]:
    """Most frequent tokens, ties broken alphabetically."""
    counts: dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ranked[:limit]]


def term_project_counts(documents: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Per-term totals keyed by project: ``term -> {project_id: count}``."""
    counts: dict[str, dict[str, int]] = {}
    for project_id, text in documents:
        for token in tokenize(text):
            per_project = counts.setdefault(token, {})
            per_project[project_id] = per_project.get(project_id, 0) + 1
    return counts
