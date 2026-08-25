import pytest

from chrono_core.store.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "b.db")
    s.init_schema()
    pid = s.upsert_project(project_id="p", name="proj", path="/tmp/p", relative_path="p")
    return s, pid


def test_report_get_list_roundtrip(store):
    s, pid = store
    bid = s.report_bug(pid, "Resume shows unrelated actions", detail="flat query", severity="high")
    assert bid.startswith("bug_")
    bug = s.get_bug(bid)
    assert bug["title"] == "Resume shows unrelated actions"
    assert bug["severity"] == "high"
    assert bug["project_name"] == "proj"
    open_bugs = s.list_bugs()
    assert [b["id"] for b in open_bugs] == [bid]
    fixed = s.update_bug(bid, status="fixed")
    assert fixed["ok"] is True and fixed["bug"]["status"] == "fixed"
    assert s.get_bug(bid)["resolved_at"]
    assert s.list_bugs(status="open") == []


def test_workspace_wide_bug_has_null_project(store):
    s, _ = store
    bid = s.report_bug(None, "cross-project issue")
    assert s.get_bug(bid)["project_name"] == "(workspace)"
    assert len(s.list_bugs()) == 1
    only_project = s.list_bugs(project_id="p")
    assert only_project == []


def test_severity_validation(store):
    s, pid = store
    with pytest.raises(ValueError, match="severity"):
        s.report_bug(pid, "bad", severity="catastrophic")


def test_search_bugs_matches_title(store):
    s, pid = store
    bid = s.report_bug(pid, "FTS syntax crash")
    hits = s.search_bugs("syntax")
    assert [h["id"] for h in hits] == [bid]
