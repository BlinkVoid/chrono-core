from __future__ import annotations

from pathlib import Path

import pytest

from chrono_core import mcp_server
from chrono_core.capture import handoff
from chrono_core.cli import build_parser
from chrono_core.config import default_db_path

CANONICAL = str(Path.home() / ".local" / "share" / "chrono-core" / "chrono.db")


def test_default_db_path_is_canonical_xdg_location():
    assert default_db_path() == CANONICAL


@pytest.mark.parametrize(
    "argv",
    [
        ["resume"],
        ["distill"],
        ["discover"],
        ["handoff", "--summary", "x"],
        ["ingest-existing-tools"],
        ["export", "markdown"],
    ],
)
def test_cli_db_path_defaults_to_canonical_location(argv: list[str]):
    args = build_parser().parse_args(argv)
    assert args.db_path == CANONICAL


def test_mcp_server_default_matches_canonical_location():
    assert mcp_server.DEFAULT_DB_PATH == CANONICAL


def test_capture_and_resume_fallbacks_match_canonical_location():
    assert handoff._default_db_path() == CANONICAL
    assert default_db_path() == CANONICAL
