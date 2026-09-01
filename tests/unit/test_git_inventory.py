"""Bounded shell-free Git inventory collection (injectable runner)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from chrono_core.workspace.inventory import (
    GIT_TIMEOUT_SECONDS,
    collect_git_inventory,
    is_git_project,
    subprocess_runner,
)


class ScriptedRunner:
    """Fake subprocess runner returning canned results per argv tail.

    Unknown tails mirror a real failing git invocation instead of raising, so
    supplementary ops keep behaving like best-effort lookups.
    """

    def __init__(self, responses: dict[tuple[str, ...], object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, argv: list[str], *, timeout: float = GIT_TIMEOUT_SECONDS):
        from chrono_core.workspace.inventory import GitCommandResult

        self.calls.append(list(argv))
        self.timeouts.append(timeout)
        result = self.responses.get(tuple(argv[3:]))
        if result is None:
            return GitCommandResult(returncode=128)
        if isinstance(result, Exception):
            raise result
        return result


def _result(stdout: str = "", returncode: int = 0):
    from chrono_core.workspace.inventory import GitCommandResult

    return GitCommandResult(returncode=returncode, stdout=stdout)


def _clean_repo_stdout() -> str:
    return "## main\n"


def test_is_git_project_accepts_directory_and_gitfile(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    assert is_git_project(repo) is True

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere/.git\n", encoding="utf-8")
    assert is_git_project(worktree) is True

    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_project(plain) is False


def test_collection_refreshes_a_gitfile_worktree(tmp_path: Path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere/.git\n", encoding="utf-8")
    runner = ScriptedRunner(
        {("status", "--porcelain=v1", "-b"): _result("## main\n")}
    )

    collected = collect_git_inventory(worktree, runner=runner)

    assert collected["is_git"] is True
    assert collected["branch"] == "main"
    assert runner.calls[0][:3] == ["git", "-C", str(worktree)]


def test_non_git_project_never_invokes_the_runner(tmp_path: Path):
    runner = ScriptedRunner()

    collected = collect_git_inventory(tmp_path / "plain", runner=runner)

    assert collected["is_git"] is False
    assert collected["branch"] is None
    assert collected["dirty"] is False
    assert collected["changed_count"] == 0
    assert collected["untracked_count"] == 0
    assert collected["error"] is None
    assert runner.calls == []


def test_collection_runs_shell_free_bounded_git_argv(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = ScriptedRunner(
        {
            ("status", "--porcelain=v1", "-b"): _result("## main\n"),
            ("log", "-1", "--pretty=%h%x1f%s"): _result("ac6368f\x1ffirst commit\n"),
            ("remote",): _result("origin\n"),
            ("remote", "get-url", "origin"): _result("https://example.com/x.git\n"),
            ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): _result(
                "origin/main\n"
            ),
        }
    )

    collected = collect_git_inventory(repo, runner=runner, timeout_seconds=3.5)

    for argv in runner.calls:
        assert argv[0] == "git"
        assert argv[1] == "-C"
        assert argv[2] == str(repo)
        assert isinstance(argv, list)
    assert set(runner.timeouts) == {3.5}
    assert collected["branch"] == "main"
    assert collected["detached"] is False
    assert collected["head_sha"] == "ac6368f"
    assert collected["head_subject"] == "first commit"
    assert collected["remote_name"] == "origin"
    assert collected["remote_url"] == "https://example.com/x.git"
    assert collected["default_branch"] == "main"
    assert collected["dirty"] is False
    assert collected["error"] is None


def test_status_counts_changed_and_untracked_lines(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    stdout = (
        "## feature...origin/feature [ahead 1]\n"
        " M src/a.py\n"
        "M  src/b.py\n"
        "?? new.txt\n"
        "?? logs/\n"
    )
    runner = ScriptedRunner(
        {("status", "--porcelain=v1", "-b"): _result(stdout)}
    )

    collected = collect_git_inventory(repo, runner=runner)

    assert collected["branch"] == "feature"
    assert collected["detached"] is False
    assert collected["dirty"] is True
    assert collected["changed_count"] == 2
    assert collected["untracked_count"] == 2


def test_detached_head_reports_no_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = ScriptedRunner(
        {("status", "--porcelain=v1", "-b"): _result("## HEAD (no branch)\n")}
    )

    collected = collect_git_inventory(repo, runner=runner)

    assert collected["detached"] is True
    assert collected["branch"] is None


def test_initial_commit_branch_is_reported_not_detached(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = ScriptedRunner(
        {
            ("status", "--porcelain=v1", "-b"): _result("## No commits yet on main\n"),
            ("log", "-1", "--pretty=%h%x1f%s"): _result("", returncode=128),
        }
    )

    collected = collect_git_inventory(repo, runner=runner)

    assert collected["branch"] == "main"
    assert collected["detached"] is False
    assert collected["head_sha"] is None
    assert collected["head_subject"] is None


def test_default_branch_falls_back_to_local_main_then_master(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = ScriptedRunner(
        {
            ("status", "--porcelain=v1", "-b"): _result("## main\n"),
            ("remote",): _result("fork\n"),
            ("remote", "get-url", "fork"): _result("git@example.com:x/y.git\n"),
            ("symbolic-ref", "--short", "refs/remotes/fork/HEAD"): _result(
                "", returncode=128
            ),
            ("rev-parse", "--verify", "refs/heads/main"): _result("main"),
        }
    )

    collected = collect_git_inventory(repo, runner=runner)
    assert collected["default_branch"] == "main"

    runner = ScriptedRunner(
        {
            ("status", "--porcelain=v1", "-b"): _result("## master\n"),
            ("remote",): _result(""),
            ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): _result(
                "", returncode=128
            ),
            ("rev-parse", "--verify", "refs/heads/main"): _result(
                "", returncode=128
            ),
            ("rev-parse", "--verify", "refs/heads/master"): _result("master"),
        }
    )
    collected = collect_git_inventory(repo, runner=runner)
    assert collected["default_branch"] == "master"
    assert collected["remote_name"] is None
    assert collected["remote_url"] is None


def test_git_failures_record_bounded_structured_errors_without_stderr(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = ScriptedRunner(
        {
            ("status", "--porcelain=v1", "-b"): _result(
                "fatal: bad object", returncode=128
            ),
        }
    )

    collected = collect_git_inventory(repo, runner=runner)

    assert collected["error"] == {"code": "git_failed", "op": "status"}
    assert "fatal" not in str(collected["error"])
    assert collected["branch"] is None


def test_timeout_and_missing_git_binary_use_stable_codes(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    from chrono_core.workspace.inventory import GitCommandResult

    timed_out = ScriptedRunner(
        {("status", "--porcelain=v1", "-b"): GitCommandResult(timed_out=True)}
    )
    collected = collect_git_inventory(repo, runner=timed_out)
    assert collected["error"]["code"] == "timeout"
    assert collected["error"]["op"] == "status"

    missing = ScriptedRunner(
        {("status", "--porcelain=v1", "-b"): GitCommandResult(missing=True)}
    )
    collected = collect_git_inventory(repo, runner=missing)
    assert collected["error"]["code"] == "git_missing"


def test_subprocess_runner_is_shell_free_and_bounded(tmp_path: Path):
    result = subprocess_runner(
        ["git", "-C", str(tmp_path), "status", "--porcelain=v1", "-b"],
        timeout=GIT_TIMEOUT_SECONDS,
    )
    assert isinstance(result.returncode, int)

    missing = subprocess_runner(["definitely-not-git-binary-xyz", "--version"])
    assert missing.missing is True


def test_real_git_repository_round_trip(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True
    )
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c",
         "user.name=t", "commit", "-q", "--allow-empty", "-m", "seed commit"],
        check=True,
        capture_output=True,
    )

    collected = collect_git_inventory(repo)

    assert collected["is_git"] is True
    assert collected["branch"] == "main"
    assert collected["detached"] is False
    assert collected["head_sha"]
    assert collected["head_subject"] == "seed commit"
    assert collected["dirty"] is False
    assert collected["error"] is None

    (repo / "tracked.txt").write_text("dirty now\n", encoding="utf-8")
    (repo / "extra.txt").write_text("untracked\n", encoding="utf-8")
    dirty = collect_git_inventory(repo)
    assert dirty["dirty"] is True
    assert dirty["changed_count"] == 1
    assert dirty["untracked_count"] == 1
