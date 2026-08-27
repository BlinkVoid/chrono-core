import json
from pathlib import Path

from chrono_core.cli import main


def test_report_list_update_flow(tmp_path: Path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "README.md").write_text("# marker\n")
    db = str(tmp_path / "db.sqlite")
    base = ["--cwd", str(proj), "--workspace-root", str(tmp_path), "--db-path", db]

    rc = main(["bug", "report", "Broken export", *base,
               "--severity", "high", "--detail", "nested dup"])
    assert rc == 0
    reported = json.loads(capsys.readouterr().out)
    bid = reported["bug"]["id"]
    assert reported["project_id"] == "proj-" + reported["project_id"].split("-")[-1]

    rc = main(["bug", "list", *base, "--json"])
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1 and listed["bugs"][0]["id"] == bid

    rc = main(["bug", "update", bid, "--status", "confirmed", *base])
    assert rc == 0
    rc = main(["bug", "update", bid, "--status", "fixed", *base])
    assert rc == 0
    capsys.readouterr()
    rc = main(["bug", "list", *base, "--status", "open", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0


def test_workspace_wide_flag(tmp_path: Path, capsys):
    db = str(tmp_path / "db.sqlite")
    rc = main(["bug", "report", "infra issue", "--db-path", db, "--workspace",
               "--cwd", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["bug"]["project_id"] is None


def test_bug_list_human_output_reports_empty_state(tmp_path: Path, capsys):
    db = str(tmp_path / "db.sqlite")

    rc = main(["bug", "list", "--db-path", db, "--status", "open"])

    assert rc == 0
    assert capsys.readouterr().out == "No open bugs.\n"
