"""One-way GitHub issue push for local bugs over the ``gh`` CLI REST bridge.

The adapter owns repository parsing, Git-origin inference, bounded
body/payload construction, subprocess execution, response validation, and the
create/update sequence. The subprocess runner is injectable so unit tests can
exercise the whole flow without a GitHub call.

Security contract: bug title and detail travel only inside the JSON request
body piped to ``gh api --input -`` through stdin. They never appear in process
arguments, shell strings, or error messages.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

GH_EXECUTABLE = "gh"
GH_TIMEOUT_SECONDS = 30.0
GIT_TIMEOUT_SECONDS = 10.0

MAX_ISSUE_TITLE_CHARS = 200
MAX_ISSUE_BODY_CHARS = 60000
TRUNCATION_SUFFIX = "\n\n[...chrono-core: truncated long detail...]"
ERROR_STDERR_CHARS = 300

BUG_BODY_MARKER_TEMPLATE = "<!-- chrono-core:bug-id={bug_id} -->"

# ``gh api`` can target GitHub Enterprise hosts as well as github.com.  Keep
# known competing Git hosts rejected, while allowing a customer-controlled
# Enterprise hostname (there is no reliable way to identify GHE from DNS).
_PUBLIC_GITHUB_HOSTS = {"github.com", "www.github.com"}
_NON_GITHUB_HOSTS = {
    "gitlab.com",
    "www.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
    "codeberg.org",
    "sourceforge.net",
}
_REPO_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
_KNOWN_STATUSES = ("open", "confirmed", "in_progress", "fixed", "wont_fix", "cancelled")

# Local lifecycle status -> (issue state, state_reason). open/confirmed/
# in_progress stay open; fixed closed as completed; wont_fix/cancelled as
# not planned.
_LIFECYCLE_STATE: dict[str, tuple[str, str | None]] = {
    "open": ("open", None),
    "confirmed": ("open", None),
    "in_progress": ("open", None),
    "fixed": ("closed", "completed"),
    "wont_fix": ("closed", "not_planned"),
    "cancelled": ("closed", "not_planned"),
}


class GitHubPushError(Exception):
    """Structured adapter failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one injectable subprocess execution."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False


Runner = Callable[..., CommandResult]


@dataclass(frozen=True)
class Repository:
    """A parsed GitHub repository reference, including GHE hostname."""

    owner: str
    repo: str
    host: str = "github.com"

    @property
    def slug(self) -> str:
        if self.host == "github.com":
            return f"{self.owner}/{self.repo}"
        return f"{self.host}/{self.owner}/{self.repo}"

    @property
    def issues_endpoint(self) -> str:
        return f"repos/{self.owner}/{self.repo}/issues"


def subprocess_runner(
    argv: list[str],
    *,
    cwd: str | None = None,
    input_text: str | None = None,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> CommandResult:
    """Run *argv* without a shell, converting exec/timeout failures to results."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return CommandResult(
            returncode=127,
            stderr=f"{argv[0]} executable not found",
            missing=True,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            returncode=124,
            stderr=f"{argv[0]} timed out after {timeout:g}s",
            timed_out=True,
        )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def _clean_owner_repo(owner: str, repo: str) -> tuple[str, str]:
    if not _REPO_LABEL.fullmatch(owner) or not _REPO_LABEL.fullmatch(repo):
        raise ValueError(f"not a GitHub OWNER/REPO reference: {owner}/{repo}")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not repo or repo in {".", ".."}:
        raise ValueError(f"not a GitHub OWNER/REPO reference: {owner}/{repo}")
    return owner, repo


def parse_repository(value: str) -> Repository:
    """Parse a GitHub repository from an explicit or remote-URL form.

    Accepted shapes: ``OWNER/REPO``, ``HOST/OWNER/REPO``,
    ``https://HOST/OWNER/REPO[/...]``, ``git://HOST/OWNER/REPO``,
    SCP-style SSH ``git@github.com:OWNER/REPO(.git)``, and
    ``ssh://git@github.com/OWNER/REPO(.git)``. Anything not clearly GitHub
    raises ``ValueError``.
    """
    if value is None:
        raise ValueError("repository is required")
    text = str(value).strip()
    if not text:
        raise ValueError("repository is required")

    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme.lower() not in {"https", "http", "ssh", "git"}:
            raise ValueError(f"unsupported repository URL scheme: {value!r}")
        host = _validate_host(parsed.hostname)
        if host is None:
            raise ValueError(f"not a GitHub repository host: {value!r}")
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            raise ValueError(f"not a GitHub OWNER/REPO reference: {value!r}")
        owner, repo = _clean_owner_repo(segments[0], segments[1])
        return Repository(owner=owner, repo=repo, host=host)

    scp_match = re.match(r"^(?:[^@/]+@)?([^/:]+):(.+)$", text)
    if scp_match:
        host, path = scp_match.group(1).lower(), scp_match.group(2)
        host = _validate_host(host)
        if host is None:
            raise ValueError(f"not a GitHub repository host: {value!r}")
        parts = [segment for segment in path.split("/") if segment]
        if len(parts) < 2:
            raise ValueError(f"not a GitHub OWNER/REPO reference: {value!r}")
        owner, repo = _clean_owner_repo(parts[0], parts[1])
        return Repository(owner=owner, repo=repo, host=host)

    segments = [segment for segment in text.split("/") if segment]
    if len(segments) == 3:
        host = _validate_host(segments[0])
        if host is None:
            raise ValueError(f"not a GitHub repository host: {value!r}")
        owner, repo = _clean_owner_repo(segments[1], segments[2])
        return Repository(owner=owner, repo=repo, host=host)
    if len(segments) != 2:
        raise ValueError(f"not a GitHub OWNER/REPO reference: {value!r}")
    owner, repo = _clean_owner_repo(segments[0], segments[1])
    return Repository(owner=owner, repo=repo)


def _validate_host(value: str | None) -> str | None:
    """Normalize a GitHub.com or GitHub Enterprise hostname."""
    host = (value or "").strip().lower().rstrip(".")
    if not host or ":" in host or not _HOST_LABEL.fullmatch(host):
        return None
    if host in _NON_GITHUB_HOSTS:
        return None
    # ``www.github.com`` is an alias of the canonical public host.
    return "github.com" if host in _PUBLIC_GITHUB_HOSTS else host


def lifecycle_state(status: str) -> tuple[str, str | None]:
    """Map a local bug status to (issue state, state_reason)."""
    if status not in _LIFECYCLE_STATE:
        raise ValueError(
            f"invalid bug status '{status}'; expected one of {_KNOWN_STATUSES}"
        )
    return _LIFECYCLE_STATE[status]


def _truncate(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    return text[: max(budget - len(TRUNCATION_SUFFIX), 0)].rstrip() + TRUNCATION_SUFFIX


def build_issue_title(bug: dict[str, Any]) -> str:
    """Return the bounded GitHub issue title derived from the local bug title."""
    title = " ".join(str(bug.get("title") or "").split())
    if len(title) > MAX_ISSUE_TITLE_CHARS:
        title = title[: MAX_ISSUE_TITLE_CHARS - 3].rstrip() + "..."
    return title


def build_issue_body(bug: dict[str, Any]) -> str:
    """Build the bounded Markdown body: detail, metadata footer, hidden marker."""
    detail = str(bug.get("detail") or "")
    footer = "\n".join(
        [
            "",
            "---",
            "",
            f"- local bug id: {bug.get('id', '')}",
            f"- project: {bug.get('project_name') or bug.get('project_id') or '(workspace)'}",
            f"- severity: {bug.get('severity', 'medium')}",
            f"- status: {bug.get('status', 'open')}",
            f"- created: {bug.get('created_at', '')}",
            f"- updated: {bug.get('updated_at', '')}",
            "",
            BUG_BODY_MARKER_TEMPLATE.format(bug_id=bug.get("id", "")),
        ]
    )
    budget = MAX_ISSUE_BODY_CHARS - len(footer)
    return _truncate(detail, max(budget, 0)) + footer


def build_create_payload(bug: dict[str, Any]) -> dict[str, Any]:
    """JSON payload for POST; GitHub creates issues in the open state only."""
    return {"title": build_issue_title(bug), "body": build_issue_body(bug)}


def build_update_payload(bug: dict[str, Any]) -> dict[str, Any]:
    """JSON payload for PATCH: title/body plus mapped open/closed state."""
    state, state_reason = lifecycle_state(str(bug.get("status") or "open"))
    payload: dict[str, Any] = {
        "title": build_issue_title(bug),
        "body": build_issue_body(bug),
        "state": state,
    }
    if state_reason is not None:
        payload["state_reason"] = state_reason
    return payload


def build_state_payload(status: str) -> dict[str, Any]:
    """JSON payload for the close/reopen PATCH after a create."""
    state, state_reason = lifecycle_state(status)
    payload: dict[str, Any] = {"state": state}
    if state_reason is not None:
        payload["state_reason"] = state_reason
    return payload


def _gh_api_argv(endpoint: str, method: str, host: str) -> list[str]:
    argv = [
        GH_EXECUTABLE,
        "api",
        "--method",
        method,
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
        endpoint,
        "--input",
        "-",
    ]
    if host != "github.com":
        # ``gh api`` needs the host explicitly for GitHub Enterprise. Keep it
        # in argv as metadata; request data remains stdin-only.
        argv[2:2] = ["--hostname", host]
    return argv


def _bounded_stderr(stderr: str) -> str:
    text = " ".join(str(stderr).split())
    if len(text) > ERROR_STDERR_CHARS:
        text = "..." + text[-ERROR_STDERR_CHARS:]
    return text


def _run_gh(
    endpoint: str,
    method: str,
    payload: dict[str, Any],
    repository: Repository,
    *,
    runner: Runner,
    timeout: float,
    sensitive_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute one gh api call through stdin and validate the issue response."""
    result = runner(
        _gh_api_argv(endpoint, method, repository.host),
        input_text=json.dumps(payload, ensure_ascii=False),
        timeout=timeout,
    )
    if result.missing:
        raise GitHubPushError(
            "gh_missing",
            f"{GH_EXECUTABLE} executable not found; install and authenticate the GitHub CLI",
        )
    if result.timed_out:
        raise GitHubPushError("timeout", f"{GH_EXECUTABLE} api timed out after {timeout:g}s")
    if result.returncode != 0:
        stderr = _redact_payload(result.stderr, payload, sensitive_values)
        raise GitHubPushError(
            "command_failed",
            f"{GH_EXECUTABLE} api failed with exit code {result.returncode}: "
            f"{_bounded_stderr(stderr)}",
        )
    return _validate_issue_response(result.stdout, repository)


def _validate_issue_response(stdout: str, repository: Repository) -> dict[str, Any]:
    """Require an issue JSON object whose number and html_url match the repo."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise GitHubPushError(
            "invalid_response", f"{GH_EXECUTABLE} api returned malformed JSON"
        ) from None
    if not isinstance(data, dict):
        raise GitHubPushError("invalid_response", "issue response is not a JSON object")
    number = data.get("number")
    html_url = data.get("html_url")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise GitHubPushError("invalid_response", "issue response has no integer number")
    if not isinstance(html_url, str) or not html_url:
        raise GitHubPushError("invalid_response", "issue response has no html_url")
    parsed_url = urlparse(html_url)
    response_host = _validate_host(parsed_url.hostname)
    if parsed_url.scheme.lower() != "https" or response_host != repository.host:
        raise GitHubPushError(
            "invalid_response",
            f"issue response html_url does not match repository {repository.slug}",
        )
    expected_path = f"/{repository.owner}/{repository.repo}/issues/{number}"
    if (
        parsed_url.path.rstrip("/").lower() != expected_path.lower()
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise GitHubPushError(
            "invalid_response", "issue response html_url does not match issue number"
        )
    return {"number": number, "html_url": html_url, "state": data.get("state")}


def _redact_payload(
    stderr: str, payload: dict[str, Any], sensitive_values: tuple[str, ...] = ()
) -> str:
    """Remove request data from CLI errors before returning them to callers."""
    redacted = str(stderr)
    values = [str(payload.get("title") or ""), str(payload.get("body") or "")]
    values.extend(sensitive_values)
    body = values[1]
    detail, separator, _footer = body.partition("\n---\n")
    if separator:
        values.append(detail)
    for value in values:
        if value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def infer_repository_from_origin(
    project_path: str | Path, *, runner: Runner
) -> Repository:
    """Infer the destination repository from the project's Git origin remote."""
    result = runner(
        ["git", "remote", "get-url", "origin"],
        cwd=str(project_path),
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.missing or result.returncode != 0:
        raise GitHubPushError(
            "origin_unavailable",
            "could not infer a repository from the project git origin; "
            "pass --repo [HOST/]OWNER/REPO",
        )
    origin = result.stdout.strip()
    if not origin:
        raise GitHubPushError(
            "origin_unavailable",
            "project git origin is empty; pass --repo [HOST/]OWNER/REPO",
        )
    try:
        return parse_repository(origin)
    except ValueError as exc:
        raise GitHubPushError(
            "origin_unavailable",
            f"project git origin is not a GitHub repository; pass --repo: {exc}",
        ) from None


def _linked_identity(bug: dict[str, Any]) -> tuple[Repository | None, int | None]:
    """Parse the stored remote identity, if any."""
    remote_url = bug.get("remote_url")
    if not remote_url:
        return None, None
    try:
        repository = parse_repository(str(remote_url))
    except ValueError as exc:
        raise GitHubPushError(
            "invalid_repo", f"linked remote_url is not a usable GitHub repository: {exc}"
        ) from None
    raw_number = bug.get("remote_issue_id")
    if raw_number is None or not str(raw_number).strip():
        raise GitHubPushError(
            "invalid_repo",
            f"linked remote_url {repository.slug} has no remote_issue_id to update",
        )
    text = str(raw_number).strip()
    if not text.isdigit():
        raise GitHubPushError(
            "invalid_repo",
            f"linked remote_issue_id {text!r} is not an issue number",
        )
    return repository, int(text)


def resolve_push_target(
    bug: dict[str, Any],
    *,
    explicit_repo: str | None,
    project_path: str | Path | None,
    runner: Runner,
) -> tuple[Repository, int | None]:
    """Decide destination repository and existing issue number for a push.

    An already-linked bug always targets its stored issue; an explicit
    repository that conflicts with that link is rejected instead of
    relinking. Unlinked project bugs infer the repo from git origin;
    workspace-wide bugs require an explicit repository.
    """
    linked_repo, issue_number = _linked_identity(bug)
    if explicit_repo:
        try:
            explicit = parse_repository(explicit_repo)
        except ValueError as exc:
            raise GitHubPushError("invalid_repo", str(exc)) from None
        if linked_repo is not None and explicit.slug.lower() != linked_repo.slug.lower():
            raise GitHubPushError(
                "repo_conflict",
                f"bug is already linked to {linked_repo.slug}; "
                f"refusing to relink to {explicit.slug}",
            )
        if linked_repo is not None:
            return linked_repo, issue_number
        return explicit, None
    if linked_repo is not None:
        return linked_repo, issue_number
    if project_path is None:
        raise GitHubPushError(
            "repo_required",
            "workspace-wide bug has no project origin; "
            "pass --repo [HOST/]OWNER/REPO",
        )
    return infer_repository_from_origin(project_path, runner=runner), None


def build_push_plan(
    bug: dict[str, Any], repository: Repository, issue_number: int | None
) -> dict[str, Any]:
    """Build the inspectable dry-run plan without executing anything."""
    if issue_number is not None:
        payload = build_update_payload(bug)
        plan = {
            "ok": True,
            "dry_run": True,
            "bug_id": bug.get("id"),
            "action": "update",
            "repository": repository.slug,
            "method": "PATCH",
            "endpoint": f"{repository.issues_endpoint}/{issue_number}",
            "payload": payload,
            "remote_url": bug.get("remote_url"),
            "remote_issue_id": str(issue_number),
            "partial": False,
        }
        return plan
    state, _state_reason = lifecycle_state(str(bug.get("status") or "open"))
    return {
        "ok": True,
        "dry_run": True,
        "bug_id": bug.get("id"),
        "action": "create",
        "repository": repository.slug,
        "method": "POST",
        "endpoint": repository.issues_endpoint,
        "payload": build_create_payload(bug),
        "remote_url": None,
        "remote_issue_id": None,
        "state_after": state,
        "partial": False,
    }


def create_issue(
    bug: dict[str, Any],
    repository: Repository,
    *,
    runner: Runner,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST a new issue from the local bug and validate the response."""
    return _run_gh(
        repository.issues_endpoint,
        "POST",
        build_create_payload(bug),
        repository,
        runner=runner,
        timeout=timeout,
        sensitive_values=(str(bug.get("title") or ""), str(bug.get("detail") or "")),
    )


def update_issue(
    bug: dict[str, Any],
    repository: Repository,
    issue_number: int,
    *,
    runner: Runner,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """PATCH an already-linked issue with current local state."""
    return _run_gh(
        f"{repository.issues_endpoint}/{issue_number}",
        "PATCH",
        build_update_payload(bug),
        repository,
        runner=runner,
        timeout=timeout,
        sensitive_values=(str(bug.get("title") or ""), str(bug.get("detail") or "")),
    )


def set_issue_state(
    repository: Repository,
    issue_number: int,
    status: str,
    *,
    runner: Runner,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """PATCH only the open/closed state (used right after a create)."""
    return _run_gh(
        f"{repository.issues_endpoint}/{issue_number}",
        "PATCH",
        build_state_payload(status),
        repository,
        runner=runner,
        timeout=timeout,
    )
