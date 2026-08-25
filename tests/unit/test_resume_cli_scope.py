import json
from pathlib import Path

from chrono_core.cli import main


def test_resume_json_reports_branch_scoping(tmp_path: Path, capsys):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    db = tmp_path / "db.sqlite"

    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)

    git("init", "-b", "feat/novel")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    git("add", ".")
    git("commit", "-m", "init")

    from chrono_core.domain.models import GitState, HandoffPayload
    from chrono_core.store.store import Store

    store = Store(db)
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_r", name="r", path=str(repo), relative_path="proj"
    )
    other = store.create_session(
        pid, HandoffPayload(summary="other"), GitState(branch="feat/platform")
    )
    store.record_next_actions(pid, other, ["unrelated platform action"])

    rc = main([
        "resume", "--cwd", str(repo), "--workspace-root", str(tmp_path),
        "--db-path", str(db), "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["branch"] == "feat/novel"
    assert out["hidden_actions"] == 1
    assert all(a["text"] != "unrelated platform action" for a in out["next_actions"])

    rc = main([
        "resume", "--cwd", str(repo), "--workspace-root", str(tmp_path),
        "--db-path", str(db), "--all", "--json",
    ])
    out = json.loads(capsys.readouterr().out)
    assert len(out["next_actions"]) == 1


def test_resume_text_footer_mentions_hidden(tmp_path: Path, capsys):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    db = tmp_path / "db.sqlite"

    from chrono_core.domain.models import GitState, HandoffPayload
    from chrono_core.store.store import Store

    store = Store(db)
    store.init_schema()
    pid = store.upsert_project(
        project_id="p_f", name="f", path=str(repo), relative_path="proj"
    )
    other = store.create_session(
        pid, HandoffPayload(summary="o"), GitState(branch="feat/other")
    )
    store.record_next_actions(pid, other, ["far away action"])

    class Args:
        cwd = str(repo)
        workspace_root = str(tmp_path)
        db_path = str(db)
        json = False
        all = False
        branch = "main"
        limit = 20

    from chrono_core.resume import resume_command

    assert resume_command(Args()) == 0
    out = capsys.readouterr().out
    assert "(+1 more on other branches: --all to show)" in out
