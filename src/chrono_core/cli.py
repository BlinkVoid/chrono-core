from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chrono_core import __version__, services
from chrono_core.capture.handoff import capture_handoff
from chrono_core.config import default_workspace_root
from chrono_core.export.markdown import export_markdown
from chrono_core.integrations.gearcore import build_gearcore_install_plan
from chrono_core.integrations.workspace_intelligence import ingest_existing_tools
from chrono_core.management.distill import distill_project
from chrono_core.management.review import review_project
from chrono_core.resume import resume_command
from chrono_core.workspace.discovery import DiscoveryOptions, discover_workspace
from chrono_core.workspace.resolver import resolve_project

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
        "--db-path", "--db", default=None, help="continuity database path"
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
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_review = sub.add_parser("review", help="run a project management review")
    p_review.add_argument("--cwd", default=".")
    p_review.add_argument("--workspace-root", default=default_workspace_root())
    p_review.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_discover = sub.add_parser("discover", help="discover workspace projects")
    p_discover.add_argument("--workspace-root", default=default_workspace_root())
    p_discover.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
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
        "--db-path", "--db", default=None, help="continuity database path"
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
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_blocker = sub.add_parser("blocker", help="manage blocker lifecycle")
    blocker_sub = p_blocker.add_subparsers(dest="blocker_command")
    p_blocker_resolve = blocker_sub.add_parser("resolve", help="mark a blocker resolved")
    p_blocker_resolve.add_argument("blocker_id", help="blocker id (see resume output)")
    p_blocker_resolve.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_blocker_cancel = blocker_sub.add_parser("cancel", help="close a blocker as cancelled")
    p_blocker_cancel.add_argument("blocker_id")
    p_blocker_cancel.add_argument("--reason", default=None)
    p_blocker_cancel.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_blocker_edit = blocker_sub.add_parser("edit", help="rewrite a blocker's title")
    p_blocker_edit.add_argument("blocker_id")
    p_blocker_edit.add_argument("--text", required=True)
    p_blocker_edit.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_blocker_reopen = blocker_sub.add_parser(
        "reopen", help="return a closed blocker to open"
    )
    p_blocker_reopen.add_argument("blocker_id")
    p_blocker_reopen.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_action = sub.add_parser("action", help="manage next-action lifecycle")
    action_sub = p_action.add_subparsers(dest="action_command")
    p_action_complete = action_sub.add_parser("complete", help="mark a next action done")
    p_action_complete.add_argument("action_id", help="next action id (see resume output)")
    p_action_complete.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_action_cancel = action_sub.add_parser(
        "cancel", help="close an action as cancelled"
    )
    p_action_cancel.add_argument("action_id")
    p_action_cancel.add_argument("--reason", default=None)
    p_action_cancel.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_action_edit = action_sub.add_parser("edit", help="rewrite an action's text")
    p_action_edit.add_argument("action_id")
    p_action_edit.add_argument("--text", required=True)
    p_action_edit.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_action_reopen = action_sub.add_parser(
        "reopen", help="return a closed action to open"
    )
    p_action_reopen.add_argument("action_id")
    p_action_reopen.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_action_supersede = action_sub.add_parser(
        "supersede", help="replace an action with corrected text, keeping both"
    )
    p_action_supersede.add_argument("action_id")
    p_action_supersede.add_argument("--text", required=True)
    p_action_supersede.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_bug = sub.add_parser("bug", help="track bugs across projects")
    bug_sub = p_bug.add_subparsers(dest="bug_command")

    p_bug_report = bug_sub.add_parser("report", help="file a bug for the project at --cwd")
    p_bug_report.add_argument("title")
    p_bug_report.add_argument("--detail", default="")
    p_bug_report.add_argument(
        "--severity", choices=["low", "medium", "high", "critical"], default="medium"
    )
    p_bug_report.add_argument(
        "--workspace", action="store_true", help="file as workspace-wide (no project)"
    )
    p_bug_report.add_argument("--cwd", default=".")
    p_bug_report.add_argument("--workspace-root", default=default_workspace_root())
    p_bug_report.add_argument("--db-path", "--db", default=None)

    p_bug_list = bug_sub.add_parser("list", help="list bugs across projects")
    p_bug_list.add_argument("--status", default="open")
    p_bug_list.add_argument("--severity", default=None)
    p_bug_list.add_argument("--project-id", default=None)
    p_bug_list.add_argument("--json", action="store_true")
    p_bug_list.add_argument("--cwd", default=".")
    p_bug_list.add_argument("--workspace-root", default=default_workspace_root())
    p_bug_list.add_argument("--db-path", "--db", default=None)

    p_bug_show = bug_sub.add_parser("show", help="show one bug")
    p_bug_show.add_argument("bug_id")
    p_bug_show.add_argument("--db-path", "--db", default=None)

    p_bug_update = bug_sub.add_parser("update", help="change bug status/severity/detail")
    p_bug_update.add_argument("bug_id")
    p_bug_update.add_argument(
        "--status", choices=["open", "confirmed", "in_progress", "fixed", "wont_fix", "cancelled"]
    )
    p_bug_update.add_argument(
        "--severity", choices=["low", "medium", "high", "critical"]
    )
    p_bug_update.add_argument("--detail")
    p_bug_update.add_argument("--cwd", default=".")
    p_bug_update.add_argument("--workspace-root", default=default_workspace_root())
    p_bug_update.add_argument("--db-path", "--db", default=None)

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
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_export = sub.add_parser("export", help="export derived continuity artifacts")
    export_sub = p_export.add_subparsers(dest="export_command")
    p_export_markdown = export_sub.add_parser("markdown", help="export project markdown")
    p_export_markdown.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )
    p_export_markdown.add_argument(
        "--output-dir",
        default="exports/markdown",
        help="directory for markdown export output",
    )
    p_export_json = export_sub.add_parser(
        "json", help="export project records (decisions, blockers, next actions) as JSON"
    )
    json_selectors = p_export_json.add_mutually_exclusive_group(required=True)
    json_selectors.add_argument("--project-id", default=None, help="export this project id")
    json_selectors.add_argument("--cwd", default=None, help="resolve the project from this path")
    p_export_json.add_argument("--workspace-root", default=default_workspace_root())
    p_export_json.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )
    p_export_json.add_argument(
        "--since",
        default=None,
        help="only include records created at or after this ISO 8601 timestamp (inclusive)",
    )
    p_export_json.add_argument(
        "--include-closed",
        action="store_true",
        help="include resolved/cancelled blockers and completed actions with their terminal status",
    )
    p_export_json.add_argument(
        "--type",
        dest="type",
        action="append",
        choices=["decisions", "blockers", "next_actions"],
        default=None,
        help="restrict output to a record type; repeatable",
    )
    p_export_graph = export_sub.add_parser(
        "graph", help="export a project's record graph (nodes and edges) as JSON"
    )
    graph_selectors = p_export_graph.add_mutually_exclusive_group(required=True)
    graph_selectors.add_argument("--project-id", default=None, help="export this project id")
    graph_selectors.add_argument("--cwd", default=None, help="resolve the project from this path")
    p_export_graph.add_argument("--workspace-root", default=default_workspace_root())
    p_export_graph.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_ingest_patterns = sub.add_parser(
        "ingest-patterns", help="ingest _MetaFactory consolidated patterns"
    )
    p_ingest_patterns.add_argument(
        "--metafactory-root",
        default=str(Path.home() / "workspace" / "_MetaFactory"),
        help="_MetaFactory checkout root",
    )
    p_ingest_patterns.add_argument(
        "--file", default=None, help="explicit patterns_library.md path"
    )
    p_ingest_patterns.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_mine = sub.add_parser(
        "mine-patterns", help="mine recurring keyword patterns across projects"
    )
    p_mine.add_argument("--min-projects", type=int, default=2)
    p_mine.add_argument("--limit", type=int, default=20)
    p_mine.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )

    p_patterns = sub.add_parser("patterns", help="inspect and manage the pattern index")
    patterns_sub = p_patterns.add_subparsers(dest="patterns_command")
    p_patterns_list = patterns_sub.add_parser("list", help="list patterns")
    p_patterns_list.add_argument("--status", default=None)
    p_patterns_list.add_argument("--limit", type=int, default=50)
    p_patterns_list.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
    )
    p_patterns_set = patterns_sub.add_parser(
        "set-status", help="transition a pattern's lifecycle status"
    )
    p_patterns_set.add_argument("pattern_id")
    p_patterns_set.add_argument(
        "status", help="candidate | validated | promoted | retired"
    )
    p_patterns_set.add_argument(
        "--db-path", "--db", default=None, help="continuity database path"
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
        store = services.open_store(args.db_path)
        result = distill_project(
            cwd=args.cwd,
            workspace_root=args.workspace_root,
            store=store,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "review":
        store = services.open_store(args.db_path)
        result = review_project(
            cwd=args.cwd,
            workspace_root=args.workspace_root,
            store=store,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "discover":
        store = None if args.no_persist else services.open_store(args.db_path)
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
        try:
            result = capture_handoff(args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "search":
        result = services.search_observations_safe(
            args.db_path, args.query, project_id=args.project_id, limit=args.limit
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "blocker":
        if args.blocker_command == "resolve":
            result = services.resolve_blocker(args.db_path, args.blocker_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "cancel":
            result = services.cancel_blocker(args.db_path, args.blocker_id, args.reason)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "edit":
            result = services.edit_blocker(args.db_path, args.blocker_id, args.text)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.blocker_command == "reopen":
            result = services.reopen_blocker(args.db_path, args.blocker_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        parser.error("blocker requires a subcommand")

    if args.command == "action":
        handlers = {
            "complete": lambda: services.complete_action(args.db_path, args.action_id),
            "cancel": lambda: services.cancel_action(args.db_path, args.action_id, args.reason),
            "edit": lambda: services.edit_action(args.db_path, args.action_id, args.text),
            "reopen": lambda: services.reopen_action(args.db_path, args.action_id),
            "supersede": lambda: services.supersede_action(args.db_path, args.action_id, args.text),
        }
        handler = handlers.get(args.action_command)
        if handler is None:
            parser.error("action requires a subcommand")
        result = handler()
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "bug":
        if args.bug_command == "report":
            result = services.report_bug(
                args.db_path, args.cwd,
                title=args.title, severity=args.severity, detail=args.detail,
                workspace_wide=args.workspace, workspace_root=args.workspace_root,
            )
        elif args.bug_command == "list":
            result = services.list_bugs(
                args.db_path, status=args.status, severity=args.severity,
                project_id=args.project_id,
            )
            if not args.json:
                for b in result["bugs"]:
                    print(f"[{b['id']}] ({b['severity']}/{b['status']}) "
                          f"{b['project_name']}: {b['title']}")
                return 0
        elif args.bug_command == "show":
            bug = services.open_store(args.db_path).get_bug(args.bug_id)
            result = {"ok": bug is not None, "bug": bug}
        elif args.bug_command == "update":
            result = services.update_bug(
                args.db_path, args.bug_id,
                status=args.status, severity=args.severity, detail=args.detail,
            )
        else:
            parser.error("bug requires a subcommand")
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.command == "ingest-existing-tools":
        store = services.open_store(args.db_path)
        result = ingest_existing_tools(
            store,
            registry_path=args.registry_path,
            workspace_root=args.workspace_root,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.command == "ingest-patterns":
        from chrono_core.integrations.metafactory import ingest_metafactory_patterns

        store = services.open_store(args.db_path)
        try:
            result = ingest_metafactory_patterns(
                store,
                metafactory_root=args.metafactory_root,
                file=args.file,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "mine-patterns":
        from chrono_core.management.patterns import mine_pattern_candidates

        result = mine_pattern_candidates(
            services.open_store(args.db_path),
            min_projects=args.min_projects,
            limit=args.limit,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "patterns":
        if args.patterns_command == "list":
            store = services.open_store(args.db_path)
            patterns = store.list_patterns(status=args.status, limit=args.limit)
            for row in patterns:
                row.pop("statement", None)
            print(json.dumps({"ok": True, "count": len(patterns), "patterns": patterns}, indent=2))
            return 0
        if args.patterns_command == "set-status":
            store = services.open_store(args.db_path)
            try:
                result = store.set_pattern_status(args.pattern_id, args.status)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        parser.error("patterns requires a subcommand")

    if args.command == "export":
        if args.export_command == "markdown":
            store = services.open_store(args.db_path)
            result = export_markdown(store, args.output_dir)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.export_command == "json":
            from chrono_core.export.json import export_json_command

            return export_json_command(args)
        if args.export_command == "graph":
            from chrono_core.export.graph import export_graph_command

            return export_graph_command(args)
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
