from __future__ import annotations

import argparse
import json
from pathlib import Path

from continuity_core import __version__
from continuity_core.capture.handoff import capture_handoff
from continuity_core.integrations.workspace_intelligence import ingest_existing_tools
from continuity_core.resume import resume_command
from continuity_core.store.store import Store
from continuity_core.workspace.discovery import DiscoveryOptions, discover_workspace
from continuity_core.workspace.resolver import resolve_project

DEFAULT_WORKSPACE_ROOT = "~/workspace"
DEFAULT_DB_PATH = "data/continuity.db"
DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY = (
    "~/workspace/tool-project-tracker/data/registry.db"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="continuity", description="Continuity Core")
    parser.add_argument("--version", action="store_true", help="print version and exit")

    sub = parser.add_subparsers(dest="command")

    p_resolve = sub.add_parser("resolve", help="resolve a project from cwd/path")
    p_resolve.add_argument("--cwd", default=".", help="working directory to resolve from")
    p_resolve.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)

    p_resume = sub.add_parser("resume", help="show resume context for a project")
    p_resume.add_argument("--cwd", default=".")
    p_resume.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    p_resume.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )
    p_resume.add_argument("--json", action="store_true", help="emit JSON")

    p_discover = sub.add_parser("discover", help="discover workspace projects")
    p_discover.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    p_discover.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )
    p_discover.add_argument(
        "--max-depth", type=int, default=3, help="maximum directory depth to scan"
    )
    p_discover.add_argument(
        "--include-provisional",
        action="store_true",
        help="include directories without project markers as provisional projects",
    )
    p_discover.add_argument(
        "--no-persist",
        action="store_true",
        help="only print discovered projects; do not upsert them into the database",
    )

    p_handoff = sub.add_parser("handoff", help="capture a session handoff")
    p_handoff.add_argument("--cwd", default=".")
    p_handoff.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    p_handoff.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )
    p_handoff.add_argument("--summary", default="", help="short handoff summary")
    p_handoff.add_argument(
        "--json", help="read structured handoff JSON from file, or '-' for stdin"
    )
    p_handoff.add_argument(
        "--decision",
        dest="decisions",
        action="append",
        default=[],
        help="decision title or JSON object",
    )
    p_handoff.add_argument(
        "--blocker",
        dest="blockers",
        action="append",
        default=[],
        help="open blocker title or JSON object",
    )
    p_handoff.add_argument(
        "--next", dest="next_actions", action="append", default=[], help="next action"
    )
    p_handoff.add_argument(
        "--test", dest="tests", action="append", default=[], help="verification run"
    )
    p_handoff.add_argument(
        "--file", dest="files_changed", action="append", default=[], help="changed file"
    )
    p_handoff.add_argument(
        "--risk", dest="risks", action="append", default=[], help="risk or uncertainty"
    )
    p_handoff.add_argument("--agent", dest="agent_name", default=None, help="agent name")

    p_ingest = sub.add_parser(
        "ingest-existing-tools", help="import workspace-intelligence registry into Continuity"
    )
    p_ingest.add_argument(
        "--registry-path",
        default=DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY,
        help="path to workspace-intelligence SQLite registry",
    )
    p_ingest.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    p_ingest.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"continuity-core {__version__}")
        return 0

    if args.command == "resolve":
        project = resolve_project(Path(args.cwd), workspace_root=Path(args.workspace_root))
        print(json.dumps(project.to_dict(), indent=2))
        return 0

    if args.command == "resume":
        return resume_command(args)

    if args.command == "discover":
        store = None if args.no_persist else Store(args.db_path)
        result = discover_workspace(
            workspace_root=args.workspace_root,
            store=store,
            options=DiscoveryOptions(
                max_depth=args.max_depth,
                include_provisional=args.include_provisional,
            ),
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.ok else 1

    if args.command == "handoff":
        if not args.summary.strip() and not args.json:
            parser.error("handoff requires --summary or --json")
        result = capture_handoff(args)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "ingest-existing-tools":
        store = Store(args.db_path)
        result = ingest_existing_tools(
            store,
            registry_path=args.registry_path,
            workspace_root=args.workspace_root,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
