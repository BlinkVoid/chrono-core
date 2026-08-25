from __future__ import annotations

import argparse
import json
from pathlib import Path

from chrono_core import __version__
from chrono_core.capture.handoff import capture_handoff
from chrono_core.config import default_db_path, default_workspace_root
from chrono_core.export.markdown import export_markdown
from chrono_core.integrations.gearcore import build_gearcore_install_plan
from chrono_core.integrations.workspace_intelligence import ingest_existing_tools
from chrono_core.management.distill import distill_project
from chrono_core.management.review import review_project
from chrono_core.resume import resume_command
from chrono_core.store.store import Store
from chrono_core.workspace.discovery import DiscoveryOptions, discover_workspace
from chrono_core.workspace.resolver import resolve_project

DEFAULT_DB_PATH = default_db_path()
DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY = str(
    Path.home() / ".local" / "state" / "workspace-intelligence" / "registry.db"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chrono", description="Chrono Core")
    parser.add_argument("--version", action="store_true", help="print version and exit")

    sub = parser.add_subparsers(dest="command")

    p_resolve = sub.add_parser("resolve", help="resolve a project from cwd/path")
    p_resolve.add_argument("--cwd", default=".", help="working directory to resolve from")
    p_resolve.add_argument("--workspace-root", default=default_workspace_root())

    p_resume = sub.add_parser("resume", help="show resume context for a project")
    p_resume.add_argument("--cwd", default=".")
    p_resume.add_argument("--workspace-root", default=default_workspace_root())
    p_resume.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )
    p_resume.add_argument("--json", action="store_true", help="emit JSON")
    p_resume.add_argument("--all", action="store_true", help="show actions from all branches")
    p_resume.add_argument("--branch", default=None, help="override the workstream branch")
    p_resume.add_argument(
        "--limit", type=int, default=20, help="max open items per category"
    )

    p_distill = sub.add_parser("distill", help="distill captured records into project state")
    p_distill.add_argument("--cwd", default=".")
    p_distill.add_argument("--workspace-root", default=default_workspace_root())
    p_distill.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    p_review = sub.add_parser("review", help="run a project management review")
    p_review.add_argument("--cwd", default=".")
    p_review.add_argument("--workspace-root", default=default_workspace_root())
    p_review.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    p_discover = sub.add_parser("discover", help="discover workspace projects")
    p_discover.add_argument("--workspace-root", default=default_workspace_root())
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
    p_handoff.add_argument("--workspace-root", default=default_workspace_root())
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

    p_search = sub.add_parser("search", help="full-text search captured observations")
    p_search.add_argument("query", help="FTS5 match expression")
    p_search.add_argument("--project-id", default=None, help="limit results to one project")
    p_search.add_argument("--limit", type=int, default=20, help="maximum results")
    p_search.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    p_blocker = sub.add_parser("blocker", help="manage blocker lifecycle")
    blocker_sub = p_blocker.add_subparsers(dest="blocker_command")
    p_blocker_resolve = blocker_sub.add_parser("resolve", help="mark a blocker resolved")
    p_blocker_resolve.add_argument("blocker_id", help="blocker id (see resume output)")
    p_blocker_resolve.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    p_action = sub.add_parser("action", help="manage next-action lifecycle")
    action_sub = p_action.add_subparsers(dest="action_command")
    p_action_complete = action_sub.add_parser("complete", help="mark a next action done")
    p_action_complete.add_argument("action_id", help="next action id (see resume output)")
    p_action_complete.add_argument(
        "--db-path", "--db", default=DEFAULT_DB_PATH, help="continuity database path"
    )

    p_ingest = sub.add_parser(
        "ingest-existing-tools", help="import workspace-intelligence registry into Continuity"
    )
    p_ingest.add_argument(
        "--registry-path",
        default=DEFAULT_WORKSPACE_INTELLIGENCE_REGISTRY,
        help="path to workspace-intelligence SQLite registry",
    )
    p_ingest.add_argument("--workspace-root", default=default_workspace_root())
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
        "--skill-path", default=None, help="override Chrono Core skill path"
    )
    p_gearcore_plan.add_argument(
        "--mcp-command", default="chrono-mcp", help="MCP server command"
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
        print(f"chrono-core {__version__}")
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

    if args.command == "review":
        store = Store(args.db_path)
        result = review_project(
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

    if args.command == "search":
        store = Store(args.db_path)
        store.init_schema()
        results = store.search_observations(
            args.query, project_id=args.project_id, limit=args.limit
        )
        result = {"ok": True, "query": args.query, "count": len(results), "results": results}
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "blocker":
        if args.blocker_command == "resolve":
            store = Store(args.db_path)
            store.init_schema()
            resolved = store.resolve_blocker(args.blocker_id)
            result = {
                "ok": resolved,
                "blocker_id": args.blocker_id,
                "status": "resolved" if resolved else "not_found",
            }
            print(json.dumps(result, indent=2))
            return 0 if resolved else 1
        parser.error("blocker requires a subcommand")

    if args.command == "action":
        if args.action_command == "complete":
            store = Store(args.db_path)
            store.init_schema()
            completed = store.complete_next_action(args.action_id)
            result = {
                "ok": completed,
                "action_id": args.action_id,
                "status": "done" if completed else "not_found",
            }
            print(json.dumps(result, indent=2))
            return 0 if completed else 1
        parser.error("action requires a subcommand")

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
