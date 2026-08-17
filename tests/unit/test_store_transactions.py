from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project


def _resolved_project(workspace: Path):
    return resolve_project(workspace / "example", workspace_root=workspace)


def test_store_uses_wal_journal_mode(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()

    mode = store._connect().execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_transaction_commits_all_writes_on_success(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()
    project = _resolved_project(tmp_path / "workspace")

    with store.transaction():
        store.get_or_create_project(project)

    other = Store(tmp_path / "test.db")
    count = other._connect().execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert count == 1


def test_transaction_rolls_back_all_writes_on_error(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()
    project = _resolved_project(tmp_path / "workspace")

    with pytest.raises(RuntimeError, match="boom"):
        with store.transaction():
            store.get_or_create_project(project)
            raise RuntimeError("boom")

    count = store._connect().execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert count == 0


def test_writes_inside_transaction_are_invisible_to_other_connections(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.init_schema()
    project = _resolved_project(tmp_path / "workspace")
    other = Store(tmp_path / "test.db")
    other.init_schema()

    with store.transaction():
        store.get_or_create_project(project)
        mid = other._connect().execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        assert mid == 0

    after = other._connect().execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert after == 1
