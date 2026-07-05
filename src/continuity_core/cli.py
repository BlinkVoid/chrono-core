from __future__ import annotations

import argparse
import json
from pathlib import Path

from continuity_core import __version__
from continuity_core.capture.handoff import capture_handoff
from continuity_core.config import DEFAULT_WORKSPACE_ROOT, default_db_path
from continuity_core.export.markdown import export_markdown
from continuity_core.integrations.gearcore import build_gearcore_install_plan
from continuity_core.integrations.workspace_intelligence import ingest_existing_tools
from continuity_core.management.distill import distill_project
from continuity_core.resume import resume_command
from continuity_core.store.store import Store
from continuity_core.workspace.discovery import DiscoveryOptions, discover_workspace
from continuity_core.workspace.resolver import resolve_project

DEFAULT_DB_PATH = default_db_path()
DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY = str(
    Path.home() / ".local" / "state" / "workspace-intelligence" / "registry.db"
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

    p_distill = sub.add_parser("distill", help="distill captured records into project state")
    p_distill.add_argument("--cwd", default=".")
    p_distill.add_argument("--workspace-root", default=DEFAULT_WORKSPACE_ROOT)
    p_distill.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

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

    p_export = sub.add_parser("export", help="export derived continuity artifacts")
    export_sub = p_export.add_subparsers(dest="export_command")
    p_export_markdown = export_sub.add_parser("markdown", help="export project markdown")
    p_export_markdown.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )
    p_export_markdown.add_argument(
        "--output-dir",
        default="exports/markdown",
        help="directory for markdown export output",
    )

    p_gearcore = sub.add_parser("gearcore", help="GearCore adapter utilities")
    gearcore_sub = p_gearcore.add_subparsers(dest="gearcore_command")
    p_gearcore_plan = gearcore_sub.add_parser(
        "install-plan", help="print GearCore registration commands"
    )
    p_gearcore_plan.add_argument(
        "--scope", choices=["global", "project"], default="global", help="GearCore scope"
    )
    p_gearcore_plan.add_argument(
        "--project-root", default=None, help="project root for project-scoped registration"
    )
    p_gearcore_plan.add_argument(
        "--skill-path", default=None, help="override Continuity Core skill path"
    )
    p_gearcore_plan.add_argument(
        "--mcp-command", default="continuity-mcp", help="MCP server command"
    )
    p_gearcore_plan.add_argument(
        "--copy", dest="symlink", action="store_false", help="copy skill instead of symlinking"
    )
    p_gearcore_plan.set_defaults(symlink=True)

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

    if args.command == "distill":
        store = Store(args.db_path)
        result = distill_project(
            cwd=args.cwd,
            workspace_root=args.workspace_root,
            store=store,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

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

    if args.command == "export":
        if args.export_command == "markdown":
            store = Store(args.db_path)
            result = export_markdown(store, args.output_dir)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        parser.error("export requires a subcommand")

    if args.command == "gearcore":
        if args.gearcore_command == "install-plan":
            result = build_gearcore_install_plan(
                scope=args.scope,
                project_root=args.project_root,
                skill_path=args.skill_path,
                symlink=args.symlink,
                mcp_command=args.mcp_command,
            ).to_dict()
            print(json.dumps(result, indent=2))
            return 0
        parser.error("gearcore requires a subcommand")

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
