import pytest

from deploysure.tools import app_store, git_tool
from deploysure.tools.project_store import ProjectError


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(app_store, "APPS_ROOT", tmp_path / "apps")
    return tmp_path


def test_connect_an_app_registers_it_without_touching_the_repo(store, tinyshop):
    repo = tinyshop[0]
    card = app_store.connect_app("Tiny Shop", str(repo))
    assert card["id"] == "tiny-shop" and card["name"] == "Tiny Shop" and card["repo_path"] == str(repo.resolve())
    assert card["latest"]["subject"] and card["analyses"] == 0
    assert git_tool.git_run(repo, "status", "--short").strip() == ""


def test_a_quoted_path_is_accepted(store, tinyshop):
    assert app_store.connect_app("Quoted", f'"{tinyshop[0]}"')["id"] == "quoted"


def test_bad_apps_are_refused_with_a_reason(store, tinyshop, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    git_tool.git_run(empty, "init", "-b", "main")
    plain = tmp_path / "plain"
    plain.mkdir()
    for name, path, status, text in [("A", tmp_path / "missing", 400, "does not exist"), ("B", plain, 400, "not a git repository"),
                                     ("C", empty, 400, "no commits"), ("!!!", tinyshop[0], 400, "name"), ("x" * 81, tinyshop[0], 400, "80")]:
        with pytest.raises(ProjectError, match=text) as err:
            app_store.connect_app(name, str(path))
        assert err.value.status == status
    assert app_store.list_apps() == []


def test_duplicate_names_conflict(store, tinyshop):
    app_store.connect_app("Shop", str(tinyshop[0]))
    with pytest.raises(ProjectError) as err:
        app_store.connect_app("shop!", str(tinyshop[0]))
    assert err.value.status == 409


def test_the_timeline_lists_commits_newest_first_with_parents_and_no_analysis(store, tinyshop):
    app_store.connect_app("Shop", str(tinyshop[0]))
    detail = app_store.get_app("shop")
    commits = detail["commits"]
    assert len(commits) == 6 and all(c["analysis"] is None for c in commits)
    contract = next(c for c in commits if "v2.2-contract-break" in c["tags"])
    assert contract["parent"] == tinyshop[1]["v1.2"] and contract["short"] == contract["sha"][:7]
    assert detail["app"]["watch"] is False


def test_a_saved_analysis_shows_up_on_its_commit(store, tinyshop):
    repo, shas = tinyshop
    app_store.connect_app("Shop", str(repo))
    report = {"old_sha": shas["v1.2"], "new_sha": shas["v2.2-contract-break"], "decision": "BLOCK", "risk_level": "CRITICAL", "risk_score": 100,
              "layer_verdict": {"primary": "connection", "confidence": "high"}, "trace": ["x"]}
    app_store.save_analysis("shop", report)
    assert app_store.load_analysis("shop", shas["v1.2"], shas["v2.2-contract-break"]) == report
    commit = next(c for c in app_store.get_app("shop")["commits"] if c["sha"] == shas["v2.2-contract-break"])
    assert commit["analysis"]["decision"] == "BLOCK" and commit["analysis"]["layer"] == "connection" and commit["analysis"]["risk_score"] == 100
    assert app_store.list_apps()[0]["analyses"] == 1


def test_an_analysis_that_was_not_saved_is_a_404(store, tinyshop):
    app_store.connect_app("Shop", str(tinyshop[0]))
    with pytest.raises(ProjectError) as err:
        app_store.load_analysis("shop", "a" * 40, "b" * 40)
    assert err.value.status == 404
    with pytest.raises(ProjectError):
        app_store.load_analysis("shop", "../x", "y")


def test_watch_is_saved(store, tinyshop):
    app_store.connect_app("Shop", str(tinyshop[0]))
    app_store.set_watch("shop", True)
    assert app_store.get_app("shop")["app"]["watch"] is True
    app_store.set_watch("shop", False)
    assert app_store.get_app("shop")["app"]["watch"] is False


def test_removing_an_app_never_touches_the_repo(store, tinyshop):
    app_store.connect_app("Shop", str(tinyshop[0]))
    app_store.delete_app("shop")
    assert app_store.list_apps() == [] and (tinyshop[0] / "backend" / "app.py").is_file()
    with pytest.raises(ProjectError) as err:
        app_store.get_app("shop")
    assert err.value.status == 404


def test_a_repo_that_disappeared_gives_a_clear_error_and_an_error_card(store, tinyshop, tmp_path):
    clone = tmp_path / "clone"
    git_tool.git_run(tinyshop[0].parent, "clone", "--quiet", str(tinyshop[0]), str(clone))
    app_store.connect_app("Gone", str(clone))
    app_store.connect_app("Fine", str(tinyshop[0]))
    import shutil
    shutil.rmtree(clone, ignore_errors=True)
    with pytest.raises(ProjectError, match="no longer exists"):
        app_store.get_app("gone")
    cards = {c["id"]: c for c in app_store.list_apps()}
    assert "no longer exists" in cards["gone"]["error"] and "error" not in cards["fine"]


def test_unsafe_ids_are_404(store):
    for bad in ("../x", "A B", "", "x" * 60):
        with pytest.raises(ProjectError) as err:
            app_store.get_app(bad)
        assert err.value.status == 404
