"""Focused tests for the one-way GitHub bug push (fakes only, no live calls)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from chrono_core import mcp_server, services
from chrono_core.cli import build_parser, main
from chrono_core.integrations import github_issues as gh
from chrono_core.integrations.github_issues import CommandResult
from chrono_core.store.store import Store

BUG_TITLE = "Broken readme link"
BUG_DETAIL = "The quickstart link returns 404."


@dataclass
class Call:
    argv: list[str]
    cwd: str | None = None
    input_text: str | None = None
    timeout: float | None = None


class FakeRunner:
    """Injectable subprocess runner that replays queued results."""

    def __init__(self, *results: CommandResult) -> None:
        self.results = list(results)
        self.calls: list[Call] = []

    def __call__(self, argv, *, cwd=None, input_text=None, timeout=None):
        self.calls.append(Call(list(argv), cwd, input_text, timeout))
        if not self.results:
            raise AssertionError("unexpected subprocess call: " + " ".join(argv))
        return self.results.pop(0)

    @property
    def last(self) -> Call:
        return self.calls[-1]


def issue_response(number: int = 7, owner: str = "octo", repo: str = "demo",
                   state: str = "open") -> str:
    return json.dumps(
        {
            "number": number,
            "html_url": f"https://github.com/{owner}/{repo}/issues/{number}",
            "state": state,
        }
    )


def _seed(
    tmp_path: Path, *, with_project: bool = True, status: str = "open"
) -> tuple[str, str, Path]:
    db_path = str(tmp_path / "chrono.db")
    store = Store(db_path)
    store.init_schema()
    project_path = tmp_path / "workspace" / "demo"
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / ".git").mkdir(exist_ok=True)
    project_id = None
    if with_project:
        project_id = store.upsert_project(
            project_id="proj_demo", name="demo",
            path=str(project_path), relative_path="demo",
        )
    bug_id = store.report_bug(
        project_id, BUG_TITLE, detail=BUG_DETAIL, severity="high"
    )
    if status != "open":
        store.update_bug(bug_id, status=status)
    return db_path, bug_id, project_path


# 1. Repository parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("octo/demo", ("octo", "demo")),
        ("github.com/octo/demo", ("octo", "demo")),
        ("https://github.com/octo/demo", ("octo", "demo")),
        ("https://github.com/octo/demo.git", ("octo", "demo")),
        ("https://github.com/octo/demo/", ("octo", "demo")),
        ("https://github.com/octo/demo/issues/12", ("octo", "demo")),
        ("git@github.com:octo/demo.git", ("octo", "demo")),
        ("ssh://git@github.com/octo/demo.git", ("octo", "demo")),
        ("git://github.com/octo/demo.git", ("octo", "demo")),
        ("ghe.example.com/octo/demo", ("octo", "demo")),
        ("https://ghe.example.com/octo/demo", ("octo", "demo")),
    ],
)
def test_parse_repository_accepts_documented_forms(value, expected):
    repo = gh.parse_repository(value)
    assert (repo.owner, repo.repo) == expected
    assert repo.issues_endpoint == f"repos/{expected[0]}/{expected[1]}/issues"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "octo",
        "octo/",
        "https://gitlab.com/octo/demo",
        "git@gitlab.com:octo/demo.git",
        "gitlab.com/octo/demo",
        "https://github.com/",
        "octo/demo/extra/deep/segments/two words",
    ],
)
def test_parse_repository_rejects_invalid_and_non_github_values(value):
    with pytest.raises(ValueError):
        gh.parse_repository(value)


# 2. Payload transport via stdin ---------------------------------------------------------


def test_create_payload_travels_through_stdin_not_argv(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(stdout=issue_response(7)))

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is True and result["action"] == "create"
    call = runner.calls[0]
    assert call.argv[0] == "gh"
    assert "--input" in call.argv and call.argv[-1] == "-"
    joined = "\x00".join(call.argv)
    assert BUG_TITLE not in joined and "quickstart" not in joined
    payload = json.loads(call.input_text)
    assert payload["title"] == BUG_TITLE
    assert BUG_DETAIL in payload["body"]
    assert f"<!-- chrono-core:bug-id={bug_id} -->" in payload["body"]


def test_enterprise_repo_uses_hostname_and_validates_enterprise_html_url(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path, with_project=False)
    runner = FakeRunner(
        CommandResult(
            stdout=json.dumps(
                {
                    "number": 9,
                    "html_url": "https://ghe.example.com/octo/demo/issues/9",
                    "state": "open",
                }
            )
        )
    )

    result = services.push_bug_to_github(
        db_path, bug_id, repo="ghe.example.com/octo/demo", runner=runner
    )

    assert result["ok"] is True
    assert result["repository"] == "ghe.example.com/octo/demo"
    assert "--hostname" in runner.last.argv
    assert runner.last.argv[runner.last.argv.index("--hostname") + 1] == "ghe.example.com"


def test_command_error_redacts_title_and_detail(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path, with_project=False)
    runner = FakeRunner(
        CommandResult(
            returncode=1,
            stderr=f"request failed: {BUG_TITLE}; {BUG_DETAIL}",
        )
    )

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert BUG_TITLE not in result["error"]
    assert BUG_DETAIL not in result["error"]


def test_update_payload_carries_state_through_stdin(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path, status="fixed")
    store = services.open_store(db_path)
    store.link_bug_remote(
        bug_id, remote_url="https://github.com/octo/demo/issues/7", remote_issue_id="7"
    )
    runner = FakeRunner(CommandResult(stdout=issue_response(7, state="closed")))

    result = services.push_bug_to_github(db_path, bug_id, runner=runner)

    assert result["ok"] is True and result["action"] == "update"
    call = runner.last
    assert "--method" in call.argv and "PATCH" in call.argv
    assert "repos/octo/demo/issues/7" in call.argv
    assert BUG_TITLE not in "\x00".join(call.argv)
    payload = json.loads(call.input_text)
    assert payload["state"] == "closed" and payload["state_reason"] == "completed"
    assert payload["title"] == BUG_TITLE and BUG_DETAIL in payload["body"]


# 3. First push creates and links; second push PATCHes -----------------------------------


def test_first_push_creates_and_links_then_second_push_patches(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    create_runner = FakeRunner(CommandResult(stdout=issue_response(7)))

    first = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=create_runner)

    assert first["ok"] is True and first["action"] == "create"
    assert first["remote_url"] == "https://github.com/octo/demo/issues/7"
    assert first["remote_issue_id"] == "7"
    assert "repos/octo/demo/issues" in create_runner.calls[0].argv
    bug = Store(db_path).get_bug(bug_id)
    assert bug["remote_url"] == "https://github.com/octo/demo/issues/7"
    assert bug["remote_issue_id"] == "7"

    patch_runner = FakeRunner(CommandResult(stdout=issue_response(7)))
    second = services.push_bug_to_github(db_path, bug_id, runner=patch_runner)

    assert second["ok"] is True and second["action"] == "update"
    assert second["repository"] == "octo/demo"
    assert len(patch_runner.calls) == 1
    assert "repos/octo/demo/issues/7" in patch_runner.calls[0].argv


# 4. Closed-create links before close PATCH; retry updates --------------------------------


def test_created_closed_bug_links_before_close_patch_and_retry_updates(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path, status="fixed")
    failing_close = FakeRunner(
        CommandResult(stdout=issue_response(7)),
        CommandResult(returncode=1, stderr="gh: HTTP 422 - state_reason invalid"),
    )

    first = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=failing_close)

    assert first["ok"] is False
    assert first["partial"] is True
    assert first["action"] == "create"
    assert first["remote_url"] == "https://github.com/octo/demo/issues/7"
    assert first["code"] == "command_failed"
    bug = Store(db_path).get_bug(bug_id)
    assert bug["remote_issue_id"] == "7"
    assert len(failing_close.calls) == 2

    retry = FakeRunner(CommandResult(stdout=issue_response(7, state="closed")))
    second = services.push_bug_to_github(db_path, bug_id, runner=retry)

    assert second["ok"] is True and second["action"] == "update"
    assert second["state"] == "closed"
    methods = [call.argv for call in retry.calls]
    assert len(methods) == 1
    assert "--method" in methods[0] and "PATCH" in methods[0]
    assert "POST" not in methods[0]


# 5. Lifecycle mapping ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("open", ("open", None)),
        ("confirmed", ("open", None)),
        ("in_progress", ("open", None)),
        ("fixed", ("closed", "completed")),
        ("wont_fix", ("closed", "not_planned")),
        ("cancelled", ("closed", "not_planned")),
    ],
)
def test_lifecycle_statuses_map_to_issue_state(status, expected):
    assert gh.lifecycle_state(status) == expected
    bug = {"id": "bug_x", "title": "t", "detail": "", "status": status}
    payload = gh.build_update_payload(bug)
    assert payload["state"] == expected[0]
    assert payload.get("state_reason") == expected[1]


# 6. Repository resolution -----------------------------------------------------------------


def test_workspace_wide_bug_requires_explicit_repo(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path, with_project=False)
    runner = FakeRunner()

    result = services.push_bug_to_github(db_path, bug_id, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "repo_required"
    assert runner.calls == []


def test_project_bug_infers_repository_from_git_origin(tmp_path):
    db_path, bug_id, project_path = _seed(tmp_path)
    runner = FakeRunner(
        CommandResult(stdout="git@github.com:octo/inferred.git\n"),
        CommandResult(stdout=issue_response(3, repo="inferred")),
    )

    result = services.push_bug_to_github(db_path, bug_id, runner=runner)

    assert result["ok"] is True
    assert result["repository"] == "octo/inferred"
    assert runner.calls[0].cwd == str(project_path)
    assert "repos/octo/inferred/issues" in runner.calls[1].argv


def test_unusable_git_origin_reports_origin_unavailable(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(returncode=128, stderr="error: no origin"))

    result = services.push_bug_to_github(db_path, bug_id, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "origin_unavailable"


# 7. Dry-run ---------------------------------------------------------------------------------


def test_dry_run_makes_no_subprocess_call_and_writes_no_remote_columns(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner()

    result = services.push_bug_to_github(
        db_path, bug_id, repo="octo/demo", dry_run=True, runner=runner
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["action"] == "create"
    assert result["repository"] == "octo/demo"
    assert result["payload"]["title"] == BUG_TITLE
    assert runner.calls == []
    bug = Store(db_path).get_bug(bug_id)
    assert bug["remote_url"] is None and bug["remote_issue_id"] is None


def test_dry_run_of_linked_bug_plans_update(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    Store(db_path).link_bug_remote(
        bug_id, remote_url="https://github.com/octo/demo/issues/7", remote_issue_id="7"
    )

    result = services.push_bug_to_github(
        db_path, bug_id, dry_run=True, runner=FakeRunner()
    )

    assert result["action"] == "update"
    assert result["method"] == "PATCH"
    assert result["endpoint"] == "repos/octo/demo/issues/7"
    assert result["remote_issue_id"] == "7"


def test_dry_run_project_without_explicit_repo_does_not_inspect_git_origin(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner()

    result = services.push_bug_to_github(db_path, bug_id, dry_run=True, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "repo_required"
    assert runner.calls == []


# 8. Structured errors ------------------------------------------------------------------------


def test_unknown_bug_returns_structured_error(tmp_path):
    db_path, _, _ = _seed(tmp_path)

    result = services.push_bug_to_github(db_path, "bug_missing")

    assert result["ok"] is False
    assert result["code"] == "bug_not_found"


def test_missing_gh_executable_returns_gh_missing(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(missing=True))

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "gh_missing"


def test_timeout_returns_structured_timeout(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(timed_out=True, returncode=124))

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "timeout"


def test_nonzero_exit_reports_bounded_stderr_without_bug_payload(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(returncode=1, stderr="gh: HTTP 404 - Not Found"))

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "command_failed"
    assert "HTTP 404" in result["error"]
    assert BUG_TITLE not in result["error"] and "quickstart" not in result["error"]


def test_malformed_response_returns_invalid_response(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(CommandResult(returncode=0, stdout="<html>not json</html>"))

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "invalid_response"


def test_response_from_wrong_repository_returns_invalid_response(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner(
        CommandResult(stdout=issue_response(7, owner="someone", repo="elsewhere"))
    )

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/demo", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "invalid_response"


def test_explicit_repo_conflicting_with_existing_link_is_rejected(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    Store(db_path).link_bug_remote(
        bug_id, remote_url="https://github.com/octo/demo/issues/7", remote_issue_id="7"
    )
    runner = FakeRunner()

    result = services.push_bug_to_github(db_path, bug_id, repo="octo/other", runner=runner)

    assert result["ok"] is False
    assert result["code"] == "repo_conflict"
    assert runner.calls == []


def test_invalid_explicit_repo_fails_before_any_subprocess(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    runner = FakeRunner()

    result = services.push_bug_to_github(
        db_path, bug_id, repo="gitlab.com/octo/demo", runner=runner
    )

    assert result["ok"] is False
    assert result["code"] == "invalid_repo"
    assert runner.calls == []


# 9. CLI parsing/dispatch and MCP handler/registration -----------------------------------------


def test_bug_push_parser_accepts_repo_and_dry_run():
    args = build_parser().parse_args(
        ["bug", "push", "bug_x", "--repo", "octo/demo", "--dry-run", "--db-path", "x.db"]
    )

    assert args.command == "bug"
    assert args.bug_command == "push"
    assert args.bug_id == "bug_x"
    assert args.repo == "octo/demo"
    assert args.dry_run is True
    assert args.db_path == "x.db"


def test_bug_push_main_dispatches_to_service_and_reports_failure(tmp_path, monkeypatch, capsys):
    seen: dict = {}

    def stub(db_path, bug_id, *, repo=None, dry_run=False):
        seen.update(db_path=db_path, bug_id=bug_id, repo=repo, dry_run=dry_run)
        return {"ok": False, "bug_id": bug_id, "error": "boom", "code": "command_failed"}

    monkeypatch.setattr(services, "push_bug_to_github", stub)

    code = main(["bug", "push", "bug_x", "--repo", "octo/demo", "--db-path", "x.db"])

    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["ok"] is False
    assert seen == {"db_path": "x.db", "bug_id": "bug_x", "repo": "octo/demo",
                    "dry_run": False}


def test_bug_push_main_exits_zero_on_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        services,
        "push_bug_to_github",
        lambda *a, **k: {"ok": True, "bug_id": a[1], "action": "create"},
    )

    code = main(["bug", "push", "bug_x", "--repo", "octo/demo"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["ok"] is True


def test_mcp_handler_matches_service_contract(monkeypatch):
    seen: dict = {}

    def stub(db_path, bug_id, *, repo=None, dry_run=False):
        seen.update(db_path=db_path, bug_id=bug_id, repo=repo, dry_run=dry_run)
        return {"ok": True, "bug_id": bug_id, "action": "create", "dry_run": dry_run}

    monkeypatch.setattr(services, "push_bug_to_github", stub)

    result = mcp_server.handle_push_bug_to_github(
        "bug_x", repo="octo/demo", dry_run=True, db_path="x.db"
    )

    assert result["ok"] is True
    assert seen == {"db_path": "x.db", "bug_id": "bug_x", "repo": "octo/demo",
                    "dry_run": True}


def test_push_bug_tool_registered_with_mutation_warning():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert "chrono_core_push_bug_to_github" in by_name
    assert "GitHub" in by_name["chrono_core_push_bug_to_github"].description


# Store.link_bug_remote -----------------------------------------------------------------------


def test_link_bug_remote_refreshes_existing_bug_and_reports_unknown(tmp_path):
    db_path, bug_id, _ = _seed(tmp_path)
    store = Store(db_path)

    linked = store.link_bug_remote(
        bug_id, remote_url="https://github.com/octo/demo/issues/7", remote_issue_id="7"
    )

    assert linked["ok"] is True
    assert linked["bug"]["remote_url"] == "https://github.com/octo/demo/issues/7"
    assert linked["bug"]["remote_issue_id"] == "7"
    assert linked["bug"]["title"] == BUG_TITLE

    missing = store.link_bug_remote(
        "bug_missing",
        remote_url="https://github.com/octo/demo/issues/8",
        remote_issue_id="8",
    )
    assert missing["ok"] is False
    assert missing["bug"] is None
    assert store.list_bugs(status=None) == [linked["bug"]]


# Bounded body construction -------------------------------------------------------------------


def test_issue_body_and_title_are_bounded():
    bug = {
        "id": "bug_big",
        "title": "x" * 1000,
        "detail": "d" * (gh.MAX_ISSUE_BODY_CHARS + 5000),
        "status": "open",
        "severity": "low",
        "project_name": "demo",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }

    title = gh.build_issue_title(bug)
    body = gh.build_issue_body(bug)

    assert len(title) <= gh.MAX_ISSUE_TITLE_CHARS
    assert len(body) <= gh.MAX_ISSUE_BODY_CHARS
    assert body.endswith("<!-- chrono-core:bug-id=bug_big -->")
    assert "local bug id: bug_big" in body
