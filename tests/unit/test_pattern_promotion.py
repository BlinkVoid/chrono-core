"""Focused tests for the reviewed GearCore pattern promotion (fakes only).

Chrono validates an already-authored skill bundle plus recorded verification
evidence, previews the exact ``gearcore add-skill`` mutation, protects the
apply with a content digest, and marks the pattern ``promoted`` only after
GearCore succeeds. Tests never mutate a real GearCore configuration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from chrono_core import services
from chrono_core.cli import build_parser, main
from chrono_core.integrations import pattern_promotion as pp
from chrono_core.integrations.pattern_promotion import CommandResult
from chrono_core.store.store import Store

SKILL_NAME = "demo-skill"
SKILL_DESCRIPTION = (
    "Use when handing off project work and a deterministic continuity record is needed."
)
SKILL_BODY = "\nDeterministic handoff workflow prose.\n"


def skill_text(name: str = SKILL_NAME, description: str = SKILL_DESCRIPTION,
               body: str = SKILL_BODY) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}"


def write_skill_bundle(
    tmp_path: Path,
    *,
    name: str = SKILL_NAME,
    dirname: str | None = None,
    text: str | None = None,
    skill_bytes: bytes | None = None,
    omit_skill: bool = False,
    skill_is_dir: bool = False,
) -> Path:
    directory = tmp_path / "bundles" / (dirname or SKILL_NAME)
    directory.mkdir(parents=True, exist_ok=True)
    if not omit_skill:
        skill_file = directory / "SKILL.md"
        if skill_is_dir:
            skill_file.mkdir(exist_ok=True)
        elif skill_bytes is not None:
            skill_file.write_bytes(skill_bytes)
        else:
            bundle_name = dirname if dirname is not None and name == SKILL_NAME else name
            skill_file.write_text(
                text if text is not None else skill_text(bundle_name), encoding="utf-8"
            )
    return directory


def write_evidence(tmp_path: Path, pattern_id: str, *, payload=None, raw: bytes | None = None,
                   name: str | None = None) -> Path:
    path = tmp_path / "evidence" / (name or f"{pattern_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_bytes(raw)
    else:
        document = payload if payload is not None else {
            "pattern_id": pattern_id,
            "baseline": [
                {"scenario": "handoff capture",
                 "observed_failure": "session state was lost between sessions"}
            ],
            "verification": [
                {"scenario": "handoff capture",
                 "observed_pass": "resume context restored the session"}
            ],
        }
        if document.get("pattern_id") == "x":
            document = {**document, "pattern_id": pattern_id}
        path.write_text(json.dumps(document), encoding="utf-8")
    return path


def seed_pattern(tmp_path: Path, status: str = "validated") -> tuple[str, str, Store]:
    db_path = str(tmp_path / "chrono.db")
    store = Store(db_path)
    store.init_schema()
    pattern_id = store.upsert_pattern(
        title="Deterministic handoff",
        statement="Persist structured handoff state between sessions.",
        category="workflow",
        status="candidate" if status == "retired" else status,
    )
    if status == "retired":
        store.set_pattern_status(pattern_id, status)
    return db_path, pattern_id, store


@dataclass
class Call:
    argv: list[str]
    timeout: float | None = None


class FakeRunner:
    """Injectable shell-free runner that replays queued results."""

    def __init__(self, *results: CommandResult) -> None:
        self.results = list(results)
        self.calls: list[Call] = []

    def __call__(self, argv, *, timeout=None):
        self.calls.append(Call(list(argv), timeout))
        if not self.results:
            raise AssertionError("unexpected subprocess call: " + " ".join(argv))
        return self.results.pop(0)

    @property
    def last(self) -> Call:
        return self.calls[-1]


def plan(db_path, pattern_id, skill_dir, evidence_path, **kwargs):
    return services.plan_pattern_promotion(
        db_path, pattern_id, skill_path=str(skill_dir), evidence_path=str(evidence_path),
        **kwargs
    )


def promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=None, **kwargs):
    return services.promote_pattern(
        db_path, pattern_id, skill_path=str(skill_dir), evidence_path=str(evidence_path),
        plan_digest=digest, runner=runner, **kwargs
    )


# 1. Valid plan is read-only and emits the exact global symlink argv ----------------------


def test_store_get_pattern_returns_row_and_none(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)

    row = store.get_pattern(pattern_id)

    assert row is not None
    assert row["id"] == pattern_id
    assert row["status"] == "validated"
    assert row["title"] == "Deterministic handoff"
    assert store.get_pattern("pat_missing") is None


def test_valid_plan_is_read_only_and_emits_exact_global_symlink_argv(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result["ok"] is True
    assert result["argv"] == [
        "gearcore", "add-skill", "--scope", "global", "--symlink", str(skill_dir),
    ]
    assert result["scope"] == "global"
    assert result["symlink"] is True
    assert result["project_root"] is None
    assert result["skill"]["name"] == SKILL_NAME
    assert result["skill"]["description"] == SKILL_DESCRIPTION
    assert result["evidence"]["baseline_count"] == 1
    assert result["evidence"]["verification_count"] == 1
    assert result["pattern"]["status"] == "validated"
    assert result["plan_digest"]
    assert store.get_pattern(pattern_id)["status"] == "validated"
    assert len(result["plan_digest"]) == 64


# 2. Project/copy plan argv and required project root --------------------------------------


def test_project_scope_plan_emits_exact_scoped_argv(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    project_root = tmp_path / "workspace" / "demo"
    project_root.mkdir(parents=True)

    result = plan(db_path, pattern_id, skill_dir, evidence_path,
                  scope="project", project_root=str(project_root))

    assert result["ok"] is True
    assert result["argv"] == [
        "gearcore", "--project", str(project_root), "add-skill",
        "--scope", "project", "--symlink", str(skill_dir),
    ]
    assert result["project_root"] == str(project_root)


def test_copy_plan_omits_symlink_flag(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path, copy=True)

    assert result["ok"] is True
    assert result["symlink"] is False
    assert "--symlink" not in result["argv"]
    assert result["argv"] == ["gearcore", "add-skill", "--scope", "global", str(skill_dir)]


def test_project_scope_without_project_root_is_rejected(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path, scope="project")

    assert result["ok"] is False
    assert result["code"] == "project_root_required"


# 3. Candidate, retired, missing, and already-promoted are structured ----------------------


@pytest.mark.parametrize(("status", "code"), [
    ("candidate", "pattern_not_eligible"),
    ("retired", "pattern_not_eligible"),
    ("promoted", "already_promoted"),
])
def test_plan_rejects_non_validated_statuses_without_side_effects(
    tmp_path, status, code
):
    db_path, pattern_id, store = seed_pattern(tmp_path, status=status)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result["ok"] is False
    assert result["code"] == code
    assert store.get_pattern(pattern_id)["status"] == status


def test_plan_missing_pattern_is_structured(tmp_path):
    db_path, _, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, "pat_missing")

    result = plan(db_path, "pat_missing", skill_dir, evidence_path)

    assert result["ok"] is False
    assert result["code"] == "pattern_not_found"


@pytest.mark.parametrize(("status", "code"), [
    ("candidate", "pattern_not_eligible"),
    ("retired", "pattern_not_eligible"),
    ("promoted", "already_promoted"),
    (None, "pattern_not_found"),
])
def test_promote_rejects_before_any_subprocess(tmp_path, status, code):
    if status is None:
        db_path, _, _ = seed_pattern(tmp_path)
        pattern_id = "pat_missing"
    else:
        db_path, pattern_id, store = seed_pattern(tmp_path, status=status)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    runner = FakeRunner()

    result = promote(db_path, pattern_id, skill_dir, evidence_path, "0" * 64, runner=runner)

    assert result["ok"] is False
    assert result["code"] == code
    assert runner.calls == []
    if status not in (None, "promoted"):
        assert Store(db_path).get_pattern(pattern_id)["status"] == status


# 4. Skill bundle validation ----------------------------------------------------------------


@pytest.mark.parametrize(("mutate", "code"), [
    ({"text": skill_text(description="Use when x\n  continued line")}, "skill_invalid_frontmatter"),
    ({"text": "---\nname: demo-skill\ndescription: Use when x\nextra: y\n---\nbody"},
     "skill_invalid_frontmatter"),
    ({"text": "---\nname: demo-skill\nname: demo-skill\ndescription: Use when x\n---\nbody"},
     "skill_invalid_frontmatter"),
    ({"text": "---\nname: demo-skill\ndescription: \"Use when x\n---\nbody"},
     "skill_invalid_frontmatter"),
    ({"text": "---\nname: Demo Skill\ndescription: Use when x\n---\nbody"}, "skill_name_invalid"),
    ({"text": "---\nname: demo_skill\ndescription: Use when x\n---\nbody"}, "skill_name_invalid"),
    ({"name": "other-name"}, "skill_name_mismatch"),
    ({"text": "---\nname: demo-skill\ndescription: Applies when x\n---\nbody"},
     "skill_description_invalid"),
    ({"text": "---\nname: demo-skill\ndescription: Use when " + "x" * 500 + "\n---\nbody"},
     "skill_description_too_long"),
    ({"text": "---\nname: demo-skill\ndescription: Use when x\n---\n   \n"}, "skill_body_empty"),
    ({"text": "name: demo-skill\ndescription: Use when x\nbody"}, "skill_invalid_frontmatter"),
    ({"omit_skill": True}, "skill_path_invalid"),
    ({"skill_is_dir": True}, "skill_path_invalid"),
    ({"skill_bytes": b"\xff\xfe\x00broken"}, "skill_invalid_encoding"),
    ({"skill_bytes": b"---\nname: demo-skill\ndescription: Use when x\n---\n"
                      + b"x" * (256 * 1024)},
     "skill_too_large"),
])
def test_skill_bundle_rejections(tmp_path, mutate, code):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path, **mutate)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result["ok"] is False
    assert result["code"] == code


def test_missing_skill_directory_is_rejected(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, tmp_path / "bundles" / "absent", evidence_path)

    assert result["ok"] is False
    assert result["code"] == "skill_path_invalid"


def test_quoted_frontmatter_scalars_are_accepted(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(
        tmp_path,
        text=(f'---\nname: "demo-skill"\ndescription: \'{SKILL_DESCRIPTION}\'\n---\n'
              f"{SKILL_BODY}"),
    )
    evidence_path = write_evidence(tmp_path, pattern_id)

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result["ok"] is True
    assert result["skill"]["name"] == SKILL_NAME
    assert result["skill"]["description"] == SKILL_DESCRIPTION


# 5. Evidence validation ---------------------------------------------------------------------


@pytest.mark.parametrize(("payload", "code"), [
    ({"pattern_id": "pat_other",
      "baseline": [{"scenario": "s", "observed_failure": "f"}],
      "verification": [{"scenario": "s", "observed_pass": "p"}]},
     "evidence_pattern_mismatch"),
    ({"pattern_id": None, "baseline": [], "verification": []}, "evidence_pattern_mismatch"),
    ({"pattern_id": "extra-key", "baseline": [], "verification": [], "extra": 1},
     "evidence_unknown_keys"),
    ({"baseline": [{"scenario": "s", "observed_failure": "f"}],
      "verification": [{"scenario": "s", "observed_pass": "p"}]},
     "evidence_unknown_keys"),
    ({"pattern_id": "x", "baseline": [], "verification": []}, "evidence_empty"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "a", "observed_failure": "f"}],
      "verification": [{"scenario": "b", "observed_pass": "p"}]},
     "evidence_scenario_mismatch"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "a", "observed_failure": "f"},
                   {"scenario": "a", "observed_failure": "f2"}],
      "verification": [{"scenario": "a", "observed_pass": "p"}]},
     "evidence_duplicate_scenario"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "a", "observed_failure": "f"}],
      "verification": [{"scenario": "a", "observed_pass": "p"},
                        {"scenario": "a", "observed_pass": "p2"}]},
     "evidence_duplicate_scenario"),
    ({"pattern_id": "x", "baseline": {"scenario": "a"},
      "verification": [{"scenario": "a", "observed_pass": "p"}]},
     "evidence_item_invalid"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "a", "observed_failure": "f", "extra": 1}],
      "verification": [{"scenario": "a", "observed_pass": "p"}]},
     "evidence_item_invalid"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "", "observed_failure": "f"}],
      "verification": [{"scenario": "a", "observed_pass": "p"}]},
     "evidence_item_invalid"),
    ({"pattern_id": "x",
      "baseline": [{"scenario": "a"}],
      "verification": [{"scenario": "a", "observed_pass": "p"}]},
     "evidence_item_invalid"),
])
def test_evidence_rejections(tmp_path, payload, code):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id, payload=payload)

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result["ok"] is False
    assert result["code"] == code


@pytest.mark.parametrize(("field", "value"), [
    ("scenario", " \t\n "),
    ("observed_failure", " \t\n "),
    ("observed_pass", " \t\n "),
])
def test_evidence_rejects_whitespace_only_required_fields(tmp_path, field, value):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    baseline = {"scenario": "handoff capture", "observed_failure": "state was lost"}
    verification = {"scenario": "handoff capture", "observed_pass": "state was restored"}
    (baseline if field != "observed_pass" else verification)[field] = value
    evidence_path = write_evidence(
        tmp_path,
        pattern_id,
        payload={
            "pattern_id": pattern_id,
            "baseline": [baseline],
            "verification": [verification],
        },
    )

    result = plan(db_path, pattern_id, skill_dir, evidence_path)

    assert result == {"ok": False, "code": "evidence_item_invalid", "pattern_id": pattern_id,
                      "pattern": Store(db_path).get_pattern(pattern_id)}


def test_evidence_malformed_encoding_and_json_and_oversize(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)

    bad_encoding = write_evidence(tmp_path, pattern_id, raw=b"\xff\xfe not utf8")
    assert plan(db_path, pattern_id, skill_dir, bad_encoding)["code"] == "evidence_invalid_encoding"

    bad_json = write_evidence(tmp_path, pattern_id, raw=b"{not json")
    assert plan(db_path, pattern_id, skill_dir, bad_json)["code"] == "evidence_invalid_json"

    oversize = write_evidence(
        tmp_path, pattern_id, raw=b'{"pad": "' + b"x" * (256 * 1024) + b'"}'
    )
    assert plan(db_path, pattern_id, skill_dir, oversize)["code"] == "evidence_too_large"


def test_missing_evidence_file_is_rejected(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)

    result = plan(db_path, pattern_id, skill_dir, tmp_path / "evidence" / "absent.json")

    assert result["ok"] is False
    assert result["code"] == "evidence_path_invalid"


# 6. Digest sensitivity -----------------------------------------------------------------------


def test_digest_changes_for_pattern_content_path_and_option_changes(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    baseline = plan(db_path, pattern_id, skill_dir, evidence_path)
    digest = baseline["plan_digest"]

    # Any change to the pattern row (including updated_at) invalidates the plan.
    store.set_pattern_status(pattern_id, "validated")
    assert plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"] != digest

    # Skill content change.
    refreshed = write_skill_bundle(tmp_path, text=skill_text(body="\nChanged prose.\n"))
    assert plan(db_path, pattern_id, refreshed, evidence_path)["plan_digest"] != digest

    # Evidence content change.
    other_evidence = write_evidence(
        tmp_path, pattern_id,
        payload={
            "pattern_id": pattern_id,
            "baseline": [
                {"scenario": "s1", "observed_failure": "f"},
                {"scenario": "s2", "observed_failure": "f2"},
            ],
            "verification": [
                {"scenario": "s1", "observed_pass": "p"},
                {"scenario": "s2", "observed_pass": "p2"},
            ],
        },
        name="changed.json",
    )
    assert plan(db_path, pattern_id, skill_dir, other_evidence)["plan_digest"] != digest

    # Skill path change with identical content.
    twin = write_skill_bundle(tmp_path, dirname="twin-dir")
    assert plan(db_path, pattern_id, twin, evidence_path)["plan_digest"] != digest

    # Registration option changes.
    assert plan(db_path, pattern_id, skill_dir, evidence_path, copy=True)["plan_digest"] != digest
    project_root = tmp_path / "ws"
    project_root.mkdir()
    assert plan(db_path, pattern_id, skill_dir, evidence_path, scope="project",
                project_root=str(project_root))["plan_digest"] != digest


# 7. Stale apply performs no subprocess --------------------------------------------------------


def test_stale_digest_performs_no_subprocess_and_keeps_status(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    stale_digest = plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"]
    write_skill_bundle(tmp_path, text=skill_text(body="\nEdited after planning.\n"))
    runner = FakeRunner(CommandResult(returncode=0, stdout="registered"))

    result = promote(db_path, pattern_id, skill_dir, evidence_path, stale_digest, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "stale_plan"
    assert runner.calls == []
    assert store.get_pattern(pattern_id)["status"] == "validated"


# 8. GearCore failures leave the pattern validated ------------------------------------------------


def test_gearcore_failures_leave_status_validated_with_bounded_stderr(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    digest = plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"]

    missing = FakeRunner(CommandResult(missing=True))
    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=missing)
    assert result["ok"] is False and result["code"] == "gearcore_missing"

    timeout = FakeRunner(CommandResult(timed_out=True, returncode=124, stderr="late"))
    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=timeout)
    assert result["ok"] is False and result["code"] == "timeout"

    noisy_stderr = "gearcore: frontmatter rejected: " + "detail " * 200
    failing = FakeRunner(CommandResult(returncode=1, stderr=noisy_stderr))
    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=failing)
    assert result["ok"] is False and result["code"] == "command_failed"
    assert result["error"] == pp.SAFE_PROVIDER_ERROR
    assert "frontmatter rejected" not in result["error"]

    assert missing.calls[0].timeout == pp.GEARCORE_TIMEOUT_SECONDS == 30.0
    assert store.get_pattern(pattern_id)["status"] == "validated"


def test_gearcore_failure_redacts_skill_and_evidence_content_from_stderr(tmp_path):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    digest = plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"]
    sensitive_skill = "DISTINCTIVE_SKILL_PROSE_DO_NOT_ECHO"
    sensitive_evidence = "DISTINCTIVE_EVIDENCE_CONTENT_DO_NOT_ECHO"
    runner = FakeRunner(CommandResult(
        returncode=1,
        stderr=f"failed while reading {sensitive_skill}: {sensitive_evidence}",
    ))

    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "command_failed"
    assert sensitive_skill not in result["error"]
    assert sensitive_evidence not in result["error"]
    assert result["error"] == "gearcore command failed; provider stderr withheld"


def test_promotion_plan_missing_database_is_structured_and_read_only(tmp_path):
    missing_db = tmp_path / "missing" / "chrono.db"
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, "pat_missing")

    result = plan(str(missing_db), "pat_missing", skill_dir, evidence_path)

    assert result == {
        "ok": False,
        "code": "database_not_found",
        "pattern_id": "pat_missing",
    }
    assert not missing_db.exists()


# 9. Successful apply runs exactly one shell-free command and marks promoted ----------------------


def test_successful_apply_marks_promoted_and_records_command(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    planned = plan(db_path, pattern_id, skill_dir, evidence_path)
    runner = FakeRunner(CommandResult(returncode=0, stdout="registered"))

    result = promote(
        db_path, pattern_id, skill_dir, evidence_path, planned["plan_digest"], runner=runner
    )

    assert result["ok"] is True
    assert result["status"] == "promoted"
    assert result["pattern"]["status"] == "promoted"
    assert result["command"]["argv"] == planned["argv"]
    assert result["command"]["returncode"] == 0
    assert result["plan_digest"] == planned["plan_digest"]
    assert len(runner.calls) == 1
    assert runner.last.argv == planned["argv"]
    assert runner.last.timeout == 30.0
    assert store.get_pattern(pattern_id)["status"] == "promoted"
    # Evidence content never travels in the command arguments.
    joined = " ".join(runner.last.argv)
    assert "observed_pass" not in joined and "handoff capture" not in joined


def test_partial_success_reports_status_write_failure_without_bundle_content(
    tmp_path, monkeypatch
):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    digest = plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"]

    def broken_status_write(self, pid, status):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(Store, "set_pattern_status", broken_status_write)
    runner = FakeRunner(CommandResult(returncode=0, stdout="registered"))

    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=runner)

    assert result["ok"] is False
    assert result["partial"] is True
    assert result["code"] == "status_write_failed"
    assert result["pattern_id"] == pattern_id
    assert result["command"]["argv"]
    serialized = json.dumps(result)
    assert SKILL_DESCRIPTION not in serialized
    assert "observed_pass" not in serialized and "handoff capture" not in serialized


# 10. Reapplying a promoted pattern performs no subprocess -----------------------------------------


def test_reapplying_promoted_pattern_performs_no_subprocess(tmp_path):
    db_path, pattern_id, store = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)
    digest = plan(db_path, pattern_id, skill_dir, evidence_path)["plan_digest"]
    first = FakeRunner(CommandResult(returncode=0, stdout="registered"))
    assert promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=first)["ok"]

    runner = FakeRunner()
    result = promote(db_path, pattern_id, skill_dir, evidence_path, digest, runner=runner)

    assert result["ok"] is False
    assert result["code"] == "already_promoted"
    assert runner.calls == []
    assert store.get_pattern(pattern_id)["status"] == "promoted"


# 11. CLI parser, dispatch, exit codes, and documentation -------------------------------


def test_promotion_plan_parser_accepts_contract_arguments():
    args = build_parser().parse_args([
        "patterns", "promotion-plan", "pat_x",
        "--skill-path", "skills/demo", "--evidence", "ev.json",
        "--scope", "project", "--project-root", "/ws/demo", "--db-path", "x.db",
    ])

    assert args.command == "patterns"
    assert args.patterns_command == "promotion-plan"
    assert args.pattern_id == "pat_x"
    assert args.skill_path == "skills/demo"
    assert args.evidence == "ev.json"
    assert args.scope == "project"
    assert args.project_root == "/ws/demo"
    assert args.symlink is True
    assert args.db_path == "x.db"


def test_promote_parser_requires_digest_and_defaults_to_global_symlink():
    args = build_parser().parse_args([
        "patterns", "promote", "pat_x", "--skill-path", "s", "--evidence", "e",
        "--plan-digest", "ab" * 32, "--copy",
    ])

    assert args.patterns_command == "promote"
    assert args.plan_digest == "ab" * 32
    assert args.scope == "global"
    assert args.symlink is False


def test_promotion_plan_cli_dispatches_and_reports_success(tmp_path, capsys):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    rc = main([
        "patterns", "promotion-plan", pattern_id,
        "--skill-path", str(skill_dir), "--evidence", str(evidence_path),
        "--db-path", db_path,
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["argv"][0] == "gearcore"


def test_promotion_plan_cli_failure_exits_non_zero(tmp_path, capsys):
    db_path, _, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)

    rc = main([
        "patterns", "promotion-plan", "pat_missing",
        "--skill-path", str(skill_dir), "--evidence", "missing.json",
        "--db-path", db_path,
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False
    assert out["code"] == "pattern_not_found"


def test_promote_cli_dispatches_with_digest_and_exit_codes(tmp_path, monkeypatch, capsys):
    seen: dict = {}

    def stub(db_path_arg, pattern_id, **kwargs):
        seen.update(db_path=db_path_arg, pattern_id=pattern_id, **kwargs)
        return {"ok": True, "pattern_id": pattern_id, "status": "promoted"}

    monkeypatch.setattr(services, "promote_pattern", stub)

    rc = main([
        "patterns", "promote", "pat_x",
        "--skill-path", "s", "--evidence", "e", "--plan-digest", "cd" * 32,
        "--scope", "project", "--project-root", "/ws/demo", "--db-path", "x.db",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True
    assert seen["db_path"] == "x.db"
    assert seen["pattern_id"] == "pat_x"
    assert seen["plan_digest"] == "cd" * 32
    assert seen["scope"] == "project"
    assert seen["project_root"] == "/ws/demo"
    assert seen["copy"] is False


def test_promote_cli_failure_exit_code(tmp_path, capsys):
    db_path, pattern_id, _ = seed_pattern(tmp_path)
    skill_dir = write_skill_bundle(tmp_path)
    evidence_path = write_evidence(tmp_path, pattern_id)

    rc = main([
        "patterns", "promote", pattern_id,
        "--skill-path", str(skill_dir), "--evidence", str(evidence_path),
        "--plan-digest", "0" * 64, "--db-path", db_path,
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["ok"] is False
    assert out["code"] == "stale_plan"


def test_documentation_matches_promotion_contract():
    readme = Path("README.md").read_text(encoding="utf-8")
    usage = Path("docs/USAGE.md").read_text(encoding="utf-8")
    contract = Path("docs/MVP_CONTRACT.md").read_text(encoding="utf-8")
    context = Path("docs/CONTEXT.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    site = Path("docs/site/index.html").read_text(encoding="utf-8")
    skill = Path("skills/chrono-core/SKILL.md").read_text(encoding="utf-8")
    for command in ("patterns promotion-plan", "patterns promote"):
        assert command in readme
        assert command in usage
        assert command in contract
    for document in (context, site, skill):
        assert "promotion" in document.lower()
    assert "[x] promote validated patterns into GearCore skills" in roadmap
    assert "--plan-digest" in contract
