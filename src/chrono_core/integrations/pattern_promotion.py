"""Validation and explicit apply boundary for promoting a pattern to GearCore.

This adapter only validates an operator-authored skill bundle and evidence
record, builds a deterministic registration plan, and executes that plan when
the caller explicitly supplies its digest.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GEARCORE_EXECUTABLE = "gearcore"
GEARCORE_TIMEOUT_SECONDS = 30.0
MAX_FILE_BYTES = 256 * 1024
MAX_DESCRIPTION_CHARS = 500
ERROR_STDERR_CHARS = 300
TRUNCATION_SUFFIX = "\n\n[...chrono-core: truncated long stderr...]"
SAFE_PROVIDER_ERROR = "gearcore command failed; provider stderr withheld"

_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_KEY = re.compile(r"^(name|description):[ \t]*(.*)$")


class PatternPromotionError(Exception):
    """Structured validation error with a stable public code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one injectable, shell-free subprocess execution."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False


Runner = Callable[..., CommandResult]


def subprocess_runner(
    argv: list[str], *, timeout: float = GEARCORE_TIMEOUT_SECONDS
) -> CommandResult:
    """Run GearCore without a shell, stdin, or unbounded wait."""
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return CommandResult(returncode=127, stderr="gearcore executable not found", missing=True)
    except subprocess.TimeoutExpired:
        return CommandResult(
            returncode=124,
            stderr=f"gearcore timed out after {timeout:g}s",
            timed_out=True,
        )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def _failure(code: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "code": code, **extra}


def _read_regular_file(
    path: Path, *, too_large: str, invalid_path: str, invalid_encoding: str
) -> bytes:
    if not path.is_file():
        raise PatternPromotionError(invalid_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PatternPromotionError(invalid_path) from exc
    if size > MAX_FILE_BYTES:
        raise PatternPromotionError(too_large)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PatternPromotionError(invalid_path) from exc


def _parse_scalar(value: str) -> str:
    # The accepted YAML subset is intentionally single-line and scalar-only.
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise PatternPromotionError("skill_invalid_frontmatter")
        inner = value[1:-1]
        if quote in inner:
            raise PatternPromotionError("skill_invalid_frontmatter")
        return inner
    if value[-1:] in {'"', "'"} or '"' in value or "'" in value:
        raise PatternPromotionError("skill_invalid_frontmatter")
    return value


def validate_skill_bundle(skill_path: str | Path) -> dict[str, Any]:
    """Validate and summarize a SKILL.md bundle without modifying it."""
    directory = Path(skill_path).expanduser().resolve()
    if not directory.is_dir():
        raise PatternPromotionError("skill_path_invalid")
    skill_file = directory / "SKILL.md"
    raw = _read_regular_file(
        skill_file,
        too_large="skill_too_large",
        invalid_path="skill_path_invalid",
        invalid_encoding="skill_invalid_encoding",
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatternPromotionError("skill_invalid_encoding") from exc

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise PatternPromotionError("skill_invalid_frontmatter")
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing is None:
        raise PatternPromotionError("skill_invalid_frontmatter")

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        content = line.rstrip("\r\n")
        match = _FRONTMATTER_KEY.fullmatch(content)
        if match is None or match.group(1) in values:
            raise PatternPromotionError("skill_invalid_frontmatter")
        values[match.group(1)] = _parse_scalar(match.group(2))
    if set(values) != {"name", "description"}:
        raise PatternPromotionError("skill_invalid_frontmatter")

    name = values["name"]
    description = values["description"]
    if not _SKILL_NAME.fullmatch(name):
        raise PatternPromotionError("skill_name_invalid")
    if name != directory.name:
        raise PatternPromotionError("skill_name_mismatch")
    if not description.startswith("Use when"):
        raise PatternPromotionError("skill_description_invalid")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise PatternPromotionError("skill_description_too_long")
    body = "".join(lines[closing + 1 :])
    if not body.strip():
        raise PatternPromotionError("skill_body_empty")
    return {
        "name": name,
        "description": description,
        "path": str(directory),
        "file_path": str(skill_file),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_evidence(evidence_path: str | Path, pattern_id: str) -> dict[str, Any]:
    """Validate the exact before/after evidence shape for one pattern."""
    path = Path(evidence_path).expanduser().resolve()
    raw = _read_regular_file(
        path,
        too_large="evidence_too_large",
        invalid_path="evidence_path_invalid",
        invalid_encoding="evidence_invalid_encoding",
    )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatternPromotionError("evidence_invalid_encoding") from exc
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PatternPromotionError("evidence_invalid_json") from exc
    if not isinstance(document, dict):
        raise PatternPromotionError("evidence_unknown_keys")
    if set(document) != {"pattern_id", "baseline", "verification"}:
        raise PatternPromotionError("evidence_unknown_keys")
    if document["pattern_id"] != pattern_id:
        raise PatternPromotionError("evidence_pattern_mismatch")
    baseline = document["baseline"]
    verification = document["verification"]
    if not isinstance(baseline, list) or not isinstance(verification, list):
        raise PatternPromotionError("evidence_item_invalid")
    if not baseline or not verification:
        raise PatternPromotionError("evidence_empty")

    def validate_items(items: Any, field: str) -> list[str]:
        expected = {"scenario", field}
        names: list[str] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != expected:
                raise PatternPromotionError("evidence_item_invalid")
            if not isinstance(item["scenario"], str) or not item["scenario"].strip():
                raise PatternPromotionError("evidence_item_invalid")
            if not isinstance(item[field], str) or not item[field].strip():
                raise PatternPromotionError("evidence_item_invalid")
            names.append(item["scenario"])
        if len(names) != len(set(names)):
            raise PatternPromotionError("evidence_duplicate_scenario")
        return names

    baseline_names = validate_items(baseline, "observed_failure")
    verification_names = validate_items(verification, "observed_pass")
    if set(baseline_names) != set(verification_names):
        raise PatternPromotionError("evidence_scenario_mismatch")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "baseline_count": len(baseline),
        "verification_count": len(verification),
    }


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_plan(
    pattern: dict[str, Any],
    *,
    skill_path: str | Path,
    evidence_path: str | Path,
    scope: str = "global",
    project_root: str | Path | None = None,
    symlink: bool = True,
) -> dict[str, Any]:
    """Build a validated, deterministic GearCore add-skill plan."""
    if scope not in {"global", "project"}:
        raise PatternPromotionError("scope_invalid")
    if scope == "project":
        if project_root is None:
            raise PatternPromotionError("project_root_required")
        resolved_root = Path(project_root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise PatternPromotionError("project_root_invalid")
    else:
        resolved_root = None
    skill = validate_skill_bundle(skill_path)
    evidence = validate_evidence(evidence_path, pattern["id"])
    resolved_skill = str(Path(skill_path).expanduser().resolve())
    argv = [GEARCORE_EXECUTABLE]
    if resolved_root is not None:
        argv.extend(["--project", str(resolved_root)])
    argv.extend(["add-skill", "--scope", scope])
    if symlink:
        argv.append("--symlink")
    argv.append(resolved_skill)
    digest_payload = {
        "pattern_id": pattern["id"],
        "status": pattern["status"],
        "updated_at": pattern["updated_at"],
        "skill_path": resolved_skill,
        "evidence_path": str(Path(evidence_path).expanduser().resolve()),
        "skill_sha256": skill["sha256"],
        "evidence_sha256": evidence["sha256"],
        "scope": scope,
        "project_root": str(resolved_root) if resolved_root is not None else None,
        "symlink": symlink,
        "argv": argv,
    }
    return {
        "ok": True,
        "pattern_id": pattern["id"],
        "pattern": pattern,
        "skill_path": resolved_skill,
        "evidence_path": str(Path(evidence_path).expanduser().resolve()),
        "skill": {"name": skill["name"], "description": skill["description"]},
        "evidence": {
            "baseline_count": evidence["baseline_count"],
            "verification_count": evidence["verification_count"],
        },
        "scope": scope,
        "project_root": str(resolved_root) if resolved_root is not None else None,
        "symlink": symlink,
        "registration_mode": "symlink" if symlink else "copy",
        "argv": argv,
        "plan_digest": _canonical_digest(digest_payload),
    }


def bounded_error(stderr: str) -> str:
    """Return a bounded summary without exposing reviewed bundle content.

    GearCore may echo a valid skill's prose, evidence, or absolute paths in
    stderr. Treat all provider stderr as sensitive rather than attempting
    brittle, content-dependent redaction.
    """
    del stderr
    return SAFE_PROVIDER_ERROR


def execute(argv: list[str], *, runner: Runner | None = None) -> CommandResult:
    return (runner or subprocess_runner)(argv, timeout=GEARCORE_TIMEOUT_SECONDS)
