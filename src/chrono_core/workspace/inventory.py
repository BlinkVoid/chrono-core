"""Bounded, shell-free collection of current Git state for a project."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False


def subprocess_runner(
    argv: list[str], *, timeout: float = GIT_TIMEOUT_SECONDS
) -> GitCommandResult:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return GitCommandResult(timed_out=True)
    except FileNotFoundError:
        return GitCommandResult(missing=True)
    return GitCommandResult(
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr
    )


def is_git_project(path: str | Path) -> bool:
    marker = Path(path) / ".git"
    try:
        return marker.is_dir() or marker.is_file()
    except OSError:
        return False


def _empty(*, is_git: bool, error: dict | None = None) -> dict:
    return {
        "is_git": is_git,
        "branch": None,
        "detached": False,
        "head_sha": None,
        "head_subject": None,
        "remote_name": None,
        "remote_url": None,
        "default_branch": None,
        "dirty": False,
        "changed_count": 0,
        "untracked_count": 0,
        "error": error,
    }


def _error(result: GitCommandResult, op: str) -> dict:
    if result.missing:
        code = "git_missing"
    elif result.timed_out:
        code = "timeout"
    else:
        code = "git_failed"
    return {"code": code, "op": op}


def _run(
    runner: Callable[..., GitCommandResult], path: Path, op_args: tuple[str, ...], timeout: float
) -> GitCommandResult:
    return runner(["git", "-C", str(path), *op_args], timeout=timeout)


def collect_git_inventory(
    path: str | Path,
    *,
    runner: Callable[..., GitCommandResult] = subprocess_runner,
    timeout_seconds: float = GIT_TIMEOUT_SECONDS,
) -> dict:
    """Collect bounded Git metadata; stderr and command output are never persisted."""
    project = Path(path)
    if not is_git_project(project):
        return _empty(is_git=False)

    try:
        status = _run(runner, project, ("status", "--porcelain=v1", "-b"), timeout_seconds)
    except FileNotFoundError:
        status = GitCommandResult(missing=True)
    except subprocess.TimeoutExpired:
        status = GitCommandResult(timed_out=True)
    except (OSError, subprocess.SubprocessError):
        status = GitCommandResult(returncode=1)
    if status.returncode != 0 or status.timed_out or status.missing:
        return _empty(is_git=True, error=_error(status, "status"))

    lines = status.stdout.splitlines()
    header = next((line[3:] for line in lines if line.startswith("## ")), "")
    detached = header == "HEAD (no branch)"
    branch: str | None = None
    if not detached and header:
        branch = header.removesuffix(" (no commits yet)").split("...", 1)[0]
        if branch.startswith("No commits yet on "):
            branch = branch.removeprefix("No commits yet on ")
    changed_count = sum(
        1
        for line in lines
        if len(line) >= 2 and not line.startswith("## ") and line[:2] != "??"
    )
    untracked_count = sum(1 for line in lines if line.startswith("??"))
    result = _empty(is_git=True)
    result.update(
        branch=branch,
        detached=detached,
        dirty=bool(changed_count or untracked_count),
        changed_count=changed_count,
        untracked_count=untracked_count,
    )

    try:
        log = _run(runner, project, ("log", "-1", "--pretty=%h%x1f%s"), timeout_seconds)
        if log.returncode == 0 and log.stdout.strip():
            head = log.stdout.strip().split("\x1f", 1)
            result["head_sha"] = head[0] or None
            result["head_subject"] = head[1] if len(head) > 1 else None
    except (OSError, subprocess.SubprocessError):
        pass

    remote_name: str | None = None
    try:
        remote = _run(runner, project, ("remote",), timeout_seconds)
        if remote.returncode == 0:
            remote_name = next(
                (line.strip() for line in remote.stdout.splitlines() if line.strip()),
                None,
            )
    except (OSError, subprocess.SubprocessError):
        remote_name = None
    result["remote_name"] = remote_name
    if remote_name:
        try:
            url = _run(runner, project, ("remote", "get-url", remote_name), timeout_seconds)
            if url.returncode == 0:
                result["remote_url"] = url.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass

    if remote_name:
        try:
            default = _run(
                runner,
                project,
                ("symbolic-ref", "--short", f"refs/remotes/{remote_name}/HEAD"),
                timeout_seconds,
            )
            if default.returncode == 0:
                value = default.stdout.strip()
                result["default_branch"] = value.rsplit("/", 1)[-1] if value else None
        except (OSError, subprocess.SubprocessError):
            pass
    if result["default_branch"] is None:
        for candidate in ("main", "master"):
            try:
                fallback = _run(
                    runner,
                    project,
                    ("rev-parse", "--verify", f"refs/heads/{candidate}"),
                    timeout_seconds,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if fallback.returncode == 0:
                result["default_branch"] = candidate
                break
    return result
