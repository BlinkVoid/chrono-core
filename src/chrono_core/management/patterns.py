"""Deterministic cross-project pattern candidate mining."""
from __future__ import annotations

import json
from typing import Any

from chrono_core.store.store import Store
from chrono_core.textutil import term_project_counts


def mine_pattern_candidates(
    store: Store, *, min_projects: int = 2, limit: int = 20
) -> dict[str, Any]:
    """Cluster recurring keywords across projects into candidate patterns.

    Terms must appear in at least ``min_projects`` distinct projects, at
    least ``min_projects`` times in each of them. A term is skipped when its
    candidate title already exists, or when an existing pattern already
    spans every project of the term; existing patterns are never
    overwritten.
    """
    conn = store._connect()
    documents: list[tuple[str, str]] = []
    for row in conn.execute(
        "SELECT project_id, title, rationale FROM decisions"
    ).fetchall():
        documents.append((row["project_id"], f"{row['title']} {row['rationale'] or ''}"))
    for row in conn.execute(
        "SELECT project_id, content FROM observations"
    ).fetchall():
        documents.append((row["project_id"], row["content"]))

    counts = term_project_counts(documents)
    qualified = [
        (term, per_project)
        for term, per_project in counts.items()
        if len(per_project) >= min_projects
        and min(per_project.values()) >= min_projects
    ]
    qualified.sort(key=lambda item: (-len(item[1]), -sum(item[1].values()), item[0]))

    existing = [
        (row["title"], set(json.loads(row["projects_json"])))
        for row in conn.execute(
            "SELECT title, projects_json FROM patterns"
        ).fetchall()
    ]

    mined: list[dict[str, Any]] = []
    skipped = 0
    for term, per_project in qualified[:limit]:
        title = f"Recurring theme: {term}"
        projects = set(per_project)
        if any(title == existing_title for existing_title, _ in existing) or any(
            projects <= covered for _existing_title, covered in existing
        ):
            skipped += 1
            continue
        project_list = sorted(per_project)
        statement = (
            f"Term '{term}' recurs across {len(project_list)} projects "
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
