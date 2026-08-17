from __future__ import annotations

from chrono_core.cli import build_parser


def test_export_markdown_parser_defaults():
    args = build_parser().parse_args(["export", "markdown"])

    assert args.command == "export"
    assert args.export_command == "markdown"
    assert args.output_dir == "exports/markdown"
