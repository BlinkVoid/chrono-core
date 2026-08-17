from __future__ import annotations

from pathlib import Path
from typing import Any

from chrono_core.domain.models import ResumeContext
from chrono_core.management.review import review_project
from chrono_core.store.store import Store


def export_markdown(store: Store, output_dir: str | Path) -> dict[str, Any]:
    """Write a compact markdown project index and one resume page per project."""
    store.init_schema()
    target = Path(output_dir)
    projects_dir = target / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    exported_projects: list[dict[str, str]] = []
    all_review_items: list[dict[str, str]] = []
    for project in store.list_projects():
        context = store.get_resume_context(project["id"])
        review = review_project(
            cwd=project["path"],
            workspace_root=Path(project["path"]).parent,
            store=store,
        )
        page_path = projects_dir / f"{project['id']}.md"
        page_path.write_text(_render_project_page(context, review), encoding="utf-8")
        for item in review["review_queue"]:
            all_review_items.append({"project": project["name"], **item})
        exported_projects.append(
            {
                "project_id": project["id"],
                "name": project["name"],
                "path": str(page_path),
                "relative_path": str(page_path.relative_to(target)),
            }
        )

    index_path = target / "Projects.md"
    index_path.write_text(_render_project_index(exported_projects), encoding="utf-8")
    review_queue_path = target / "ReviewQueue.md"
    review_queue_path.write_text(_render_review_queue(all_review_items), encoding="utf-8")

    return {
        "ok": True,
        "output_dir": str(target),
        "index_path": str(index_path),
        "review_queue_path": str(review_queue_path),
        "exported_count": len(exported_projects),
        "projects": exported_projects,
    }


def _render_project_index(projects: list[dict[str, str]]) -> str:
    lines = ["# Projects", ""]
    if not projects:
        lines.append("No projects exported.")
        return "\n".join(lines) + "\n"

    for project in projects:
        lines.append(f"- [{project['name']}]({project['relative_path']})")
    return "\n".join(lines) + "\n"


def _render_project_page(context: ResumeContext, review: dict[str, Any] | None = None) -> str:
    lines = [
        f"# {context.project_name}",
        "",
        f"- Project ID: `{context.project_id}`",
        f"- Path: `{context.project_path}`",
        f"- Status: {context.current_status or 'Unknown'}",
        "",
    ]

    if context.summary:
        lines.extend(["## Latest Session", "", context.summary, ""])

    _append_items(lines, "Open Blockers", context.active_blockers, "title")
    _append_items(lines, "Next Actions", context.next_actions, "text")
    _append_items(lines, "Recent Decisions", context.recent_decisions, "title")
    if review:
        lines.extend(["## Health Review", "", f"- Status: {review['health']['status']}"])
        lines.append(f"- Canonical phase: {review['canonical_phase']}")
        lines.append("")
        _append_queue(lines, review.get("review_queue", []))

    return "\n".join(lines).rstrip() + "\n"


def _append_items(
    lines: list[str], heading: str, items: list[dict[str, Any]], content_key: str
) -> None:
    if not items:
        return
    lines.extend([f"## {heading}", ""])
    for item in items:
        content = str(item.get(content_key, "")).strip()
        if content:
            lines.append(f"- {content}")
    lines.append("")


def _append_queue(lines: list[str], items: list[dict[str, Any]]) -> None:
    if not items:
        return
    lines.extend(["## Review Queue", ""])
    for item in items:
        summary = str(item.get("summary", "")).strip()
        target = str(item.get("target", "")).strip()
        item_type = str(item.get("type", "review")).strip()
        if summary:
            lines.append(f"- [{item_type}] {target}: {summary}")
    lines.append("")


def _render_review_queue(items: list[dict[str, str]]) -> str:
    lines = ["# Review Queue", ""]
    if not items:
        lines.append("No review items.")
        return "\n".join(lines) + "\n"
    for item in items:
        project = item.get("project", "unknown")
        item_type = item.get("type", "review")
        target = item.get("target", "")
        summary = item.get("summary", "")
        severity = item.get("severity", "normal")
        lines.append(f"- **{project}** [{severity}] {item_type} `{target}`: {summary}")
    return "\n".join(lines) + "\n"
