from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chrono_core.store.store import Store
from chrono_core.workspace.resolver import PROJECT_MARKERS, ResolvedProject

DEFAULT_SKIP_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}


@dataclass(frozen=True)
class DiscoveryOptions:
    max_depth: int = 3
    include_provisional: bool = False
    skip_dirs: frozenset[str] = frozenset(DEFAULT_SKIP_DIRS)


@dataclass
class DiscoveryResult:
    ok: bool
    workspace_root: str
    discovered_count: int = 0
    persisted_count: int = 0
    skipped_count: int = 0
    projects: list[ResolvedProject] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "workspace_root": self.workspace_root,
            "discovered_count": self.discovered_count,
            "persisted_count": self.persisted_count,
            "skipped_count": self.skipped_count,
            "projects": [project.to_dict() for project in self.projects],
            "skipped": list(self.skipped),
        }


def discover_workspace(
    *,
    workspace_root: str | Path,
    store: Store | None = None,
    options: DiscoveryOptions | None = None,
) -> DiscoveryResult:
    """Discover projects below a workspace root and optionally persist them."""
    workspace = Path(workspace_root).expanduser().resolve()
    opts = options or DiscoveryOptions()
    result = DiscoveryResult(ok=True, workspace_root=str(workspace))

    if not workspace.exists():
        result.ok = False
        result.skipped_count = 1
        result.skipped.append({"reason": "workspace_root_not_found", "path": str(workspace)})
        return result
    if not workspace.is_dir():
        result.ok = False
        result.skipped_count = 1
        result.skipped.append({"reason": "workspace_root_not_directory", "path": str(workspace)})
        return result

    projects = list(_iter_projects(workspace, opts))
    result.projects.extend(projects)
    result.discovered_count = len(projects)

    if store is not None:
        store.init_schema()
        for project in projects:
            store.get_or_create_project(project)
        result.persisted_count = len(projects)

    return result


def _iter_projects(workspace: Path, options: DiscoveryOptions) -> list[ResolvedProject]:
    projects: list[ResolvedProject] = []
    seen_paths: set[Path] = set()

    def visit(path: Path, depth: int) -> None:
        if depth > options.max_depth:
            return

        try:
            children = sorted(path.iterdir(), key=lambda child: child.name)
        except OSError:
            return

        marker = _first_marker(path)
        if marker and path not in seen_paths:
            projects.append(_project_from_path(path, workspace=workspace, marker=marker))
            seen_paths.add(path)
        elif options.include_provisional and depth > 0 and path not in seen_paths:
            projects.append(_project_from_path(path, workspace=workspace, marker="provisional"))
            seen_paths.add(path)

        for child in children:
            if not child.is_dir():
                continue
            if _should_skip(child, options.skip_dirs):
                continue
            visit(child, depth + 1)

    visit(workspace, 0)
    return projects


def _project_from_path(path: Path, *, workspace: Path, marker: str) -> ResolvedProject:
    relative_path = str(path.relative_to(workspace))
    return ResolvedProject(
        name=path.name,
        path=str(path),
        relative_path=relative_path,
        marker=marker,
        known=False,
    )


def _first_marker(path: Path) -> str | None:
    for marker in PROJECT_MARKERS:
        if (path / marker).exists():
            return marker
    return None


def _should_skip(path: Path, skip_dirs: frozenset[str]) -> bool:
    name = path.name
    return name in skip_dirs or (name.startswith(".") and name not in {".config"})
