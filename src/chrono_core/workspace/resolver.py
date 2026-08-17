from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

STRONG_MARKERS = (
    ".git",
    "hive.project.json",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
)

# Weak markers only count when no ancestor carries a strong marker, so a
# docs/ folder with a README cannot shadow the repository root above it.
WEAK_MARKERS = ("README.md",)

PROJECT_MARKERS = (*STRONG_MARKERS, *WEAK_MARKERS)


@dataclass(frozen=True)
class ResolvedProject:
    name: str
    path: str
    relative_path: str
    marker: str
    known: bool = False
    project_id: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "project_id", make_project_id(self.relative_path))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "relative_path": self.relative_path,
            "marker": self.marker,
            "known": self.known,
            "project_id": self.project_id,
        }


def make_project_id(relative_path: str) -> str:
    """Return a deterministic, URL-safe project id for a workspace-relative path."""
    normalized = relative_path.replace("\\", "/").strip("/")
    if not normalized:
        normalized = "workspace-root"
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:10]
    return f"{Path(normalized).name}-{digest}"


def resolve_project(cwd: Path, *, workspace_root: Path) -> ResolvedProject:
    """Resolve a project by walking upward from *cwd* until a project marker is found."""
    current = cwd.expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()

    candidates = [current, *current.parents]
    weak_candidate: tuple[Path, str] | None = None
    for candidate in candidates:
        if not _is_within(candidate, workspace):
            break
        marker = _first_of(candidate, STRONG_MARKERS)
        if marker:
            return _resolved(candidate, workspace, marker)
        if weak_candidate is None:
            weak_marker = _first_of(candidate, WEAK_MARKERS)
            if weak_marker:
                weak_candidate = (candidate, weak_marker)

    if weak_candidate is not None:
        return _resolved(weak_candidate[0], workspace, weak_candidate[1])

    if _is_within(current, workspace):
        return ResolvedProject(
            name=current.name,
            path=str(current),
            relative_path=str(current.relative_to(workspace)),
            marker="provisional",
            known=False,
        )

    raise ValueError(f"{current} is outside workspace root {workspace}")


def _resolved(candidate: Path, workspace: Path, marker: str) -> ResolvedProject:
    return ResolvedProject(
        name=candidate.name,
        path=str(candidate),
        relative_path=str(candidate.relative_to(workspace)),
        marker=marker,
        known=False,
    )


def _first_of(path: Path, markers: tuple[str, ...]) -> str | None:
    for marker in markers:
        if (path / marker).exists():
            return marker
    return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
