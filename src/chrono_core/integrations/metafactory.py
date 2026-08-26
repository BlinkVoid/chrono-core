"""Ingest _MetaFactory consolidated pattern snapshots into the pattern index."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chrono_core.store.store import Store

_HEADER_RE = re.compile(r"^## Pattern:\s*(.+?)\s*$", re.MULTILINE)
_CATEGORY_RE = re.compile(r"\*\*Category\*\*:\s*(.+?)\s*$", re.MULTILINE)
_PROJECTS_RE = re.compile(r"\*\*Projects\*\*:\s*(.+?)\s*$", re.MULTILINE)
_STATEMENT_MARKER = "**Pattern Statement**:"
# Worktree-family markers used by MetaFactory frequency notes.
_MARKERS_RE = re.compile(r"[†‡]")


def parse_patterns_library(text: str) -> list[dict[str, Any]]:
    """Parse a patterns_library.md into pattern dicts (best effort per block)."""
    patterns: list[dict[str, Any]] = []
    headers = list(_HEADER_RE.finditer(text))
    for index, match in enumerate(headers):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[start:end]

        title = match.group(1).strip()
        category_match = _CATEGORY_RE.search(block)
        category = category_match.group(1).strip() if category_match else None

        projects: list[str] = []
        projects_match = _PROJECTS_RE.search(block)
        if projects_match:
            raw = _MARKERS_RE.sub("", projects_match.group(1))
            projects = [part.strip() for part in raw.split(",") if part.strip()]

        statement_start = block.find(_STATEMENT_MARKER)
        statement = ""
        if statement_start >= 0:
            body = block[statement_start + len(_STATEMENT_MARKER) :]
            statement = "\n".join(line.strip() for line in body.strip().splitlines()).strip()

        patterns.append(
            {
                "title": title,
                "statement": statement,
                "category": category,
                "projects": projects,
            }
        )
    return patterns


def find_latest_patterns_file(root: Path) -> Path | None:
    """Newest consolidated/<stamp>/patterns_library.md, or None."""
    consolidated = Path(root) / "consolidated"
    if not consolidated.is_dir():
        return None
    for entry in sorted(consolidated.iterdir(), reverse=True):
        candidate = entry / "patterns_library.md"
        if candidate.is_file():
            return candidate
    return None


def default_metafactory_root() -> Path:
    return Path.home() / "workspace" / "_MetaFactory"


def ingest_metafactory_patterns(
    store: Store,
    *,
    metafactory_root: str | Path | None = None,
    file: str | Path | None = None,
) -> dict[str, Any]:
    """Ingest one snapshot's patterns as validated, source='metafactory'."""
    if file is not None:
        source = Path(file)
    else:
        resolved = Path(metafactory_root) if metafactory_root else default_metafactory_root()
        found = find_latest_patterns_file(resolved)
        if found is None:
            raise ValueError(f"no consolidated patterns_library.md under {resolved}")
        source = found
    if not source.is_file():
        raise ValueError(f"patterns file not found: {source}")

    parsed = parse_patterns_library(source.read_text(encoding="utf-8"))
    ingested: list[dict[str, Any]] = []
    with store.transaction():
        for pattern in parsed:
            pattern_id = store.upsert_pattern(
                title=pattern["title"],
                statement=pattern["statement"],
                category=pattern["category"],
                source="metafactory",
                source_ref=str(source),
                projects=pattern["projects"],
                status="validated",
            )
            ingested.append({"id": pattern_id, "title": pattern["title"], "status": "validated"})
    return {
        "ok": True,
        "source_file": str(source),
        "ingested": len(ingested),
        "patterns": ingested,
    }
