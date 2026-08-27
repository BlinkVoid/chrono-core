"""Deterministic cross-project pattern candidate mining."""
from __future__ import annotations

from typing import Any

from chrono_core.store.store import Store
from chrono_core.textutil import phrase_project_counts

MINABLE_OBSERVATION_KINDS = frozenset({"lesson", "pattern", "pattern_candidate"})


def mine_pattern_candidates(
    store: Store, *, min_projects: int = 2, limit: int = 20
) -> dict[str, Any]:
    """Cluster recurring phrases across projects into candidate patterns.

    Phrases must appear in at least ``min_projects`` distinct projects. Only
    explicitly semantic observations are considered; decisions, operational
    handoff data, and importer telemetry are excluded. A phrase
    whose candidate title already exists is skipped, never overwritten.
    """
    conn = store._connect()
    documents: list[tuple[str, str]] = []
    placeholders = ", ".join("?" for _kind in MINABLE_OBSERVATION_KINDS)
    for row in conn.execute(
        f"SELECT project_id, content FROM observations WHERE kind IN ({placeholders})",
        tuple(sorted(MINABLE_OBSERVATION_KINDS)),
    ).fetchall():
        documents.append((row["project_id"], row["content"]))

    counts = phrase_project_counts(documents)
    qualified = [
        (term, per_project)
        for term, per_project in counts.items()
        if len(per_project) >= min_projects
    ]
    qualified.sort(key=lambda item: (-len(item[1]), -sum(item[1].values()), item[0]))

    mined: list[dict[str, Any]] = []
    skipped = 0
    for phrase, per_project in qualified[:limit]:
        title = f"Recurring pattern: {phrase}"
        if conn.execute("SELECT 1 FROM patterns WHERE title = ?", (title,)).fetchone():
            skipped += 1
            continue
        project_list = sorted(per_project)
        statement = (
            f"Phrase '{phrase}' recurs across {len(project_list)} projects "
            f"({', '.join(project_list)}); totals: "
            f"{', '.join(f'{pid}={n}' for pid, n in sorted(per_project.items()))}."
        )
        pattern_id = store.upsert_pattern(
            title=title,
            statement=statement,
            category=None,
            source="mined",
            source_ref=None,
            projects=project_list,
            status="candidate",
        )
        mined.append({"id": pattern_id, "title": title})

    return {"ok": True, "mined": mined, "skipped_existing": skipped}
