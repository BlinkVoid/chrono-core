from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core.integrations.metafactory import (
    find_latest_patterns_file,
    ingest_metafactory_patterns,
    parse_patterns_library,
)

SAMPLE = """# Patterns Library — 2026-08-01_090633

Intro text ignored.

---

## Pattern: Fail-Closed Gating at Trust Boundaries

**Category**: security
**Frequency**: 5 projects (3 codebases)
**Projects**: FigmentLab†, gear-sandbox

**Pattern Statement**:
At any boundary where unsafe input could pass, the default is rejection.

**Implementation Variants**:
- FigmentLab†: validators reject unknown features rather than guessing.

**When to Use**:
Any system processing untrusted input.

---

## Pattern: Single Client Boundary

**Category**: architecture
**Frequency**: 2 projects
**Projects**: ProjectMik, GearCore

**Pattern Statement**:
All external provider calls flow through exactly one client abstraction.
"""


def write_snapshot(root: Path, stamp: str, text: str) -> Path:
    snap = root / "consolidated" / stamp
    snap.mkdir(parents=True)
    path = snap / "patterns_library.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_patterns_library_extracts_blocks():
    patterns = parse_patterns_library(SAMPLE)

    assert [p["title"] for p in patterns] == [
        "Fail-Closed Gating at Trust Boundaries",
        "Single Client Boundary",
    ]
    first = patterns[0]
    assert first["category"] == "security"
    assert first["projects"] == ["FigmentLab", "gear-sandbox"]
    assert first["statement"].startswith("At any boundary")
    assert "validators reject unknown features" in first["statement"]
    assert "Any system processing untrusted input." in first["statement"]


def test_find_latest_picks_newest_snapshot(tmp_path: Path):
    write_snapshot(tmp_path, "2026-07-31_154240", SAMPLE)
    newest = write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)

    assert find_latest_patterns_file(tmp_path) == newest
    assert find_latest_patterns_file(tmp_path / "missing") is None


def test_ingest_is_idempotent_and_marks_validated(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    snapshot = write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)

    first = ingest_metafactory_patterns(store, metafactory_root=tmp_path)
    second = ingest_metafactory_patterns(store, file=snapshot)

    assert first["ok"] and second["ok"]
    assert first["source_file"] == str(snapshot)
    assert first["ingested"] == 2
    assert second["ingested"] == 2  # updated in place
    rows = store.list_patterns()
    assert len(rows) == 2
    assert all(r["status"] == "validated" for r in rows)


def test_ingest_does_not_regress_promoted(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    write_snapshot(tmp_path, "2026-08-01_090633", SAMPLE)
    ingest_metafactory_patterns(store, metafactory_root=tmp_path)
    pid = store.list_patterns()[0]["id"]
    store.set_pattern_status(pid, "promoted")

    ingest_metafactory_patterns(store, metafactory_root=tmp_path)

    statuses = {r["id"]: r["status"] for r in store.list_patterns()}
    assert statuses[pid] == "promoted"


def test_ingest_missing_sources_raise_value_error(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    with pytest.raises(ValueError):
        ingest_metafactory_patterns(store, metafactory_root=tmp_path / "nope")
    with pytest.raises(ValueError):
        ingest_metafactory_patterns(store, file=tmp_path / "absent.md")


def test_ingest_parses_nothing_into_zero_without_error(tmp_path: Path):
    from chrono_core.store.store import Store

    store = Store(tmp_path / "chrono.db")
    store.init_schema()
    write_snapshot(tmp_path, "2026-08-01_090633", "# Patterns Library\n\nNo blocks.\n")

    result = ingest_metafactory_patterns(store, metafactory_root=tmp_path)

    assert result == {
        "ok": True,
        "source_file": str(tmp_path / "consolidated" / "2026-08-01_090633" / "patterns_library.md"),
        "ingested": 0,
        "patterns": [],
    }
