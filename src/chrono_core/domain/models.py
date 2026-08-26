from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTION_STATUSES = ("open", "done", "cancelled", "superseded")
BLOCKER_STATUSES = ("open", "resolved", "cancelled")
BUG_SEVERITIES = ("low", "medium", "high", "critical")
PATTERN_STATUSES = ("candidate", "validated", "promoted", "retired")
BUG_STATUSES = ("open", "confirmed", "in_progress", "fixed", "wont_fix", "cancelled")


@dataclass(frozen=True)
class ResumeContext:
    project_id: str
    project_name: str
    project_path: str
    current_status: str = ""
    summary: str = ""
    active_blockers: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)
    branch: str = ""
    hidden_actions: int = 0
    hidden_blockers: int = 0
    recommended_patterns: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "current_status": self.current_status,
            "summary": self.summary,
            "active_blockers": self.active_blockers,
            "next_actions": self.next_actions,
            "recent_decisions": self.recent_decisions,
            "branch": self.branch,
            "hidden_actions": self.hidden_actions,
            "hidden_blockers": self.hidden_blockers,
            "recommended_patterns": self.recommended_patterns,
        }


@dataclass(frozen=True)
class GitState:
    branch: str | None = None
    head: str | None = None
    dirty: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "head": self.head,
            "dirty": self.dirty,
        }


@dataclass(frozen=True)
class HandoffPayload:
    summary: str
    files_changed: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "files_changed": self.files_changed,
            "tests": self.tests,
            "decisions": self.decisions,
            "blockers": self.blockers,
            "next_actions": self.next_actions,
            "risks": self.risks,
        }
