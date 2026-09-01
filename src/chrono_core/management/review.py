from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chrono_core.management.distill import (
    bug_pressure,
    distill_registered_project,
    high_severity_bug_count,
)
from chrono_core.store.store import Store
from chrono_core.workspace.resolver import resolve_project

PHASE_PATTERN = re.compile(r"\bPhase\s+(\d+)\b", re.IGNORECASE)
CHECKBOX_PATTERN = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+)")
# Review is intentionally scoped to the project's root Markdown and its
# canonical ``docs/`` tree. These limits keep management review bounded when a
# project contains generated or bulk-data trees.
MAX_REVIEW_DOCUMENTS = 256
MAX_REVIEW_DOCUMENT_BYTES = 1_048_576
MAX_REVIEW_TOTAL_BYTES = 4_194_304
MAX_REVIEW_CANDIDATES = MAX_REVIEW_DOCUMENTS * 4
PRUNED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        ".worktrees",
        "worktree",
        "worktrees",
        "build",
        "dist",
        "generated",
        "generated-docs",
        "coverage",
        "node_modules",
        "vendor",
        "third_party",
        "third-party",
        "dependency",
        "dependencies",
        "deps",
        "data",
        "dataset",
        "datasets",
        "artifacts",
        "export",
        "exports",
        "output",
        "outputs",
        "honeycomb",
        "_archive_projects",
    }
)
PRIORITY_DOCUMENTS = (
    "docs/ROADMAP.md",
    "docs/CONTEXT.md",
    "ROADMAP.md",
    "CONTEXT.md",
)


def review_project(
    *,
    cwd: str | Path,
    workspace_root: str | Path,
    store: Store,
) -> dict[str, Any]:
    """Run a deterministic management review for one project.

    The review reconciles docs against the roadmap phase, reports stale or
    contradictory project-state claims, emits health/advice, and builds a wiki
    review queue. It is deliberately local and repeatable so management sessions
    do not depend on an LLM.
    """
    store.init_schema()
    project = resolve_project(Path(cwd), workspace_root=Path(workspace_root))
    project_id = store.get_or_create_project(project)
    distillation = distill_registered_project(project_id=project_id, store=store)
    store.update_project_state(
        project_id,
        phase=distillation["phase"],
        summary=distillation["summary"],
    )
    registered_project = store.get_project(project_id)
    if registered_project is None:
        raise RuntimeError(f"registered project disappeared: {project_id}")
    return review_registered_project(project=registered_project, store=store)


def review_registered_project(
    *, project: dict[str, Any], store: Store
) -> dict[str, Any]:
    """Review an existing project without resolving, registering, or updating it.

    This read-only view deliberately uses the catalog's stored path verbatim.
    It supports derived Markdown export even when that path is a symlink, while
    ``review_project`` retains the standalone command's explicit mutation flow.
    """
    project_id = str(project["id"])
    distillation = distill_registered_project(project_id=project_id, store=store)
    context = store.get_resume_context(project_id)
    scanned_documents = _scan_documents(Path(str(project["path"])))
    canonical_phase = _canonical_phase(scanned_documents) or _phase_from_project_state(distillation)
    documents = [
        {key: value for key, value in doc.items() if key != "_text"}
        for doc in scanned_documents
    ]
    findings = _find_doc_drift(documents, canonical_phase)
    health = _build_health(context, findings, store, project_id)
    advice = _build_advice(context, findings, canonical_phase, store, project_id)
    review_queue = _build_review_queue(context, findings)

    return {
        "ok": True,
        "project_id": project_id,
        "project_name": context.project_name,
        "project_path": context.project_path,
        "canonical_phase": canonical_phase,
        "distillation": distillation,
        "documents": documents,
        "findings": findings,
        "health": health,
        "improvement_advice": advice,
        "review_queue": review_queue,
    }


def _scan_documents(project_path: Path) -> list[dict[str, Any]]:
    """Read a deterministic, bounded set of project Markdown documents.

    The scope is root-level Markdown plus Markdown recursively below ``docs/``.
    Hidden, generated, dependency, worktree, and bulk-data directories are
    pruned before descending. Canonical roadmap/context files are considered
    first so the document and byte ceilings do not hide project state.
    """
    if not project_path.exists() or not project_path.is_dir():
        return []

    docs: list[dict[str, Any]] = []
    total_bytes = 0
    for candidate_index, path in enumerate(
        _iter_document_paths(project_path), start=1
    ):
        if candidate_index > MAX_REVIEW_CANDIDATES:
            break
        if len(docs) >= MAX_REVIEW_DOCUMENTS:
            break
        remaining_bytes = MAX_REVIEW_TOTAL_BYTES - total_bytes
        if remaining_bytes <= 0:
            break
        allowed_bytes = min(MAX_REVIEW_DOCUMENT_BYTES, remaining_bytes)
        try:
            with path.open("rb") as handle:
                raw = handle.read(allowed_bytes + 1)
        except OSError:
            continue
        if len(raw) > allowed_bytes:
            continue
        total_bytes += len(raw)
        text = raw.decode("utf-8", errors="replace")
        relative_path = path.relative_to(project_path).as_posix()
        docs.append(
            {
                "path": relative_path,
                "title": _title_for_doc(text, path),
                "phases": _phase_mentions(text),
                "current_phase_claims": _current_phase_claims(text),
                "line_count": len(text.splitlines()),
                "_text": text,
            }
        )
    return docs


def _iter_document_paths(project_path: Path):
    """Yield scoped Markdown paths in deterministic canonical-first order."""
    yielded: set[Path] = set()
    for relative_path in PRIORITY_DOCUMENTS:
        path = project_path / relative_path
        if _is_markdown_file(path):
            yielded.add(path)
            yield path

    for path in _sorted_children(project_path):
        if path.name == "docs" or path in yielded:
            continue
        if _is_markdown_file(path):
            yielded.add(path)
            yield path

    docs_path = project_path / "docs"
    if docs_path.is_dir() and not docs_path.is_symlink():
        yield from _iter_docs_paths(docs_path, yielded)


def _iter_docs_paths(docs_path: Path, yielded: set[Path]):
    stack = [docs_path]
    while stack:
        current = stack.pop()
        directories: list[Path] = []
        for path in _sorted_children(current):
            if path in yielded or path.is_symlink():
                continue
            if _is_markdown_file(path):
                yielded.add(path)
                yield path
            elif _is_directory(path) and not _should_prune_directory(path.name):
                directories.append(path)
        stack.extend(reversed(directories))


def _sorted_children(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir(), key=lambda child: (child.name.casefold(), child.name))
    except OSError:
        return []


def _is_markdown_file(path: Path) -> bool:
    return not path.is_symlink() and _is_file(path) and path.suffix.lower() == ".md"


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _should_prune_directory(name: str) -> bool:
    return name.startswith(".") or name.casefold() in PRUNED_DIRS


def _title_for_doc(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem


def _phase_mentions(text: str) -> list[str]:
    phases = {f"Phase {match.group(1)}" for match in PHASE_PATTERN.finditer(text)}
    return sorted(phases, key=lambda value: int(value.split()[1]))


def _current_phase_claims(text: str) -> list[str]:
    lines = text.splitlines()
    claims: set[str] = set()
    for index, line in enumerate(lines):
        if "current phase" in line.lower() or "current status" in line.lower():
            window = "\n".join(lines[index : index + 5])
            phases = _phase_mentions(window)
            if phases:
                claims.add(phases[-1])
    return sorted(claims, key=lambda value: int(value.split()[1]))


def _canonical_phase(documents: list[dict[str, Any]]) -> str | None:
    roadmap = next((doc for doc in documents if doc["path"].lower().endswith("roadmap.md")), None)
    if roadmap is None:
        return None
    text = str(roadmap.get("_text", ""))
    if text:
        return _canonical_phase_from_text(text)
    phases = roadmap.get("phases", [])
    return phases[-1] if phases else None


def _phase_from_project_state(distillation: dict[str, Any]) -> str:
    phase = str(distillation.get("phase") or "unknown")
    if phase == "blocked":
        return "blocked"
    if phase == "active":
        return "active"
    return "unknown"


def _canonical_phase_from_text(text: str) -> str | None:
    current_phase: str | None = None
    phase_order: list[str] = []
    phase_checks: dict[str, list[bool]] = {}

    for line in text.splitlines():
        heading_match = re.match(r"^\s*##\s+Phase\s+(\d+)\b", line, re.IGNORECASE)
        if heading_match:
            current_phase = f"Phase {heading_match.group(1)}"
            phase_order.append(current_phase)
            phase_checks.setdefault(current_phase, [])
            continue
        checkbox_match = CHECKBOX_PATTERN.match(line)
        if checkbox_match and current_phase is not None:
            phase_checks.setdefault(current_phase, []).append(
                checkbox_match.group("mark").lower() == "x"
            )

    completed_indexes = [
        index
        for index, phase in enumerate(phase_order)
        if phase_checks.get(phase) and all(phase_checks[phase])
    ]
    if completed_indexes:
        latest_completed = max(completed_indexes)
        for phase in phase_order[latest_completed + 1 :]:
            checks = phase_checks.get(phase, [])
            if checks and not all(checks):
                return phase
        return phase_order[latest_completed]

    for phase in phase_order:
        checks = phase_checks.get(phase, [])
        if checks and not all(checks):
            return phase
    if phase_order:
        return phase_order[-1]
    return None


def _find_doc_drift(
    documents: list[dict[str, Any]], canonical_phase: str | None
) -> list[dict[str, Any]]:
    if not canonical_phase or canonical_phase in {"active", "blocked", "unknown"}:
        return []

    findings: list[dict[str, Any]] = []
    for doc in documents:
        claims = doc.get("current_phase_claims", [])
        if claims and canonical_phase not in claims:
            findings.append(
                {
                    "kind": "stale_doc",
                    "severity": "medium",
                    "path": doc["path"],
                    "message": (
                        f"Current phase claim {', '.join(claims)} "
                        f"differs from {canonical_phase}."
                    ),
                }
            )
        phases = set(doc.get("phases", []))
        if claims and any(claim != canonical_phase for claim in claims):
            findings.append(
                {
                    "kind": "contradictory_doc",
                    "severity": "medium",
                    "path": doc["path"],
                    "message": (
                        "Document phase claim conflicts with roadmap "
                        f"canonical phase {canonical_phase}."
                    ),
                }
            )
        elif (
            phases
            and canonical_phase not in phases
            and doc["path"].lower().endswith("context.md")
        ):
            findings.append(
                {
                    "kind": "stale_doc",
                    "severity": "low",
                    "path": doc["path"],
                    "message": f"Context doc omits canonical phase {canonical_phase}.",
                }
            )
    return findings


def _build_health(
    context: Any,
    findings: list[dict[str, Any]],
    store: Store,
    project_id: str,
) -> dict[str, Any]:
    open_blockers = len(context.active_blockers)
    open_actions = len(context.next_actions)
    stale_docs = sum(1 for finding in findings if finding["kind"] == "stale_doc")
    contradictions = sum(1 for finding in findings if finding["kind"] == "contradictory_doc")
    penalty = bug_pressure(store, project_id)
    bug_count = high_severity_bug_count(store, project_id)
    if open_blockers:
        status = "blocked"
    elif contradictions or stale_docs:
        status = "needs_review"
    elif open_actions:
        status = "active"
    else:
        status = "healthy"
    return {
        "status": status,
        "score": max(0, 100 - penalty),
        "open_high_severity_bugs": bug_count,
        "open_blockers": open_blockers,
        "open_actions": open_actions,
        "recent_decisions": len(context.recent_decisions),
        "stale_docs": stale_docs,
        "contradictions": contradictions,
    }


def _build_advice(
    context: Any,
    findings: list[dict[str, Any]],
    canonical_phase: str | None,
    store: Store,
    project_id: str,
) -> list[dict[str, str]]:
    advice: list[dict[str, str]] = []
    for blocker in context.active_blockers:
        title = str(blocker.get("title", "")).strip()
        if title:
            advice.append(
                {
                    "priority": "high",
                    "advice": f"Resolve or explicitly defer blocker: {title}",
                }
            )
    bug_count = high_severity_bug_count(store, project_id)
    if bug_count:
        advice.append(
            {
                "priority": "high",
                "advice": f"{bug_count} open high-severity bug(s) need triage",
            }
        )
    if findings:
        advice.append(
            {
                "priority": "medium",
                "advice": f"Reconcile docs to canonical phase {canonical_phase}.",
            }
        )
    if context.next_actions:
        action = str(context.next_actions[0].get("text", "")).strip()
        if action:
            advice.append({"priority": "normal", "advice": f"Next action: {action}"})
    if not advice:
        advice.append({"priority": "normal", "advice": "No immediate management action."})
    return advice


def _build_review_queue(context: Any, findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    queue: list[dict[str, str]] = []
    for finding in findings:
        queue.append(
            {
                "type": finding["kind"],
                "target": finding["path"],
                "severity": finding["severity"],
                "summary": finding["message"],
            }
        )
    for blocker in context.active_blockers:
        queue.append(
            {
                "type": "blocker",
                "target": str(blocker.get("id", "")),
                "severity": "high",
                "summary": str(blocker.get("title", "")),
            }
        )
    for action in context.next_actions:
        queue.append(
            {
                "type": "next_action",
                "target": str(action.get("id", "")),
                "severity": "normal",
                "summary": str(action.get("text", "")),
            }
        )
    return queue
