from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from continuity_core.management.distill import distill_project
from continuity_core.store.store import Store
from continuity_core.workspace.resolver import resolve_project

PHASE_PATTERN = re.compile(r"\bPhase\s+(\d+)\b", re.IGNORECASE)
CHECKBOX_PATTERN = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+)")
SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}


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
    distillation = distill_project(cwd=cwd, workspace_root=workspace_root, store=store)
    context = store.get_resume_context(project_id)
    scanned_documents = _scan_documents(Path(project.path))
    canonical_phase = _canonical_phase(scanned_documents) or _phase_from_project_state(distillation)
    documents = [
        {key: value for key, value in doc.items() if key != "_text"}
        for doc in scanned_documents
    ]
    findings = _find_doc_drift(documents, canonical_phase)
    health = _build_health(context, findings)
    advice = _build_advice(context, findings, canonical_phase)
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
    if not project_path.exists():
        return []

    docs: list[dict[str, Any]] = []
    for path in sorted(project_path.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
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


def _build_health(context: Any, findings: list[dict[str, Any]]) -> dict[str, Any]:
    open_blockers = len(context.active_blockers)
    open_actions = len(context.next_actions)
    stale_docs = sum(1 for finding in findings if finding["kind"] == "stale_doc")
    contradictions = sum(1 for finding in findings if finding["kind"] == "contradictory_doc")
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
        "open_blockers": open_blockers,
        "open_actions": open_actions,
        "recent_decisions": len(context.recent_decisions),
        "stale_docs": stale_docs,
        "contradictions": contradictions,
    }


def _build_advice(
    context: Any, findings: list[dict[str, Any]], canonical_phase: str | None
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
