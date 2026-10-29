import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from deploysure import server, server_apps
from deploysure.tools import app_store, git_tool
from deploysure.tools.project_store import ProjectError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(app_store, "APPS_ROOT", tmp_path / "apps")


def events(response) -> list[dict]:
    async def collect():
        return [chunk async for chunk in response.body_iterator]
    return [json.loads(frame[6:]) for frame in asyncio.run(collect())]


def connect(tinyshop):
    return server_apps.new_app(server_apps.NewApp(name="Tiny Shop", repo_path=str(tinyshop[0])))


def test_connect_list_and_open_an_app(tinyshop):
    card = connect(tinyshop)
    assert card["id"] == "tiny-shop"
    assert [a["id"] for a in server_apps.apps()] == ["tiny-shop"]
    detail = server_apps.app_detail("tiny-shop")
    assert len(detail["commits"]) == 6 and detail["app"]["watch"] is False


def test_a_bad_repo_is_a_400_and_an_unknown_app_a_404(tmp_path):
    with pytest.raises(ProjectError) as err:
        server_apps.new_app(server_apps.NewApp(name="x", repo_path=str(tmp_path / "nope")))
    assert err.value.status == 400
    with pytest.raises(ProjectError) as err:
        server_apps.app_detail("nope")
    assert err.value.status == 404


def test_connecting_needs_exactly_one_of_a_folder_or_a_github_link(tinyshop):
    for body, text in [(server_apps.NewApp(name="x"), "either"), (server_apps.NewApp(name="x", repo_path=str(tinyshop[0]), repo_url="https://github.com/a/b"), "either"),
                       (server_apps.NewApp(repo_path=str(tinyshop[0])), "name"), (server_apps.NewApp(repo_url="https://example.com/a/b"), "github.com/owner/repo")]:
        with pytest.raises(ProjectError, match=text) as err:
            server_apps.new_app(body)
        assert err.value.status == 400
    assert server_apps.apps() == []


def test_a_github_link_is_downloaded_through_the_route(tinyshop, tmp_path, monkeypatch):
    git_tool.git_run(tmp_path, "clone", "--quiet", str(tinyshop[0]), str(tmp_path / "remote"))
    monkeypatch.setattr(app_store, "clone_source", lambda link: str(tmp_path / "remote"))
    card = server_apps.new_app(server_apps.NewApp(repo_url="https://github.com/someone/tinyshop"))
    assert card["id"] == "tinyshop" and server_apps.app_detail("tinyshop")["app"]["source"] == "github"
    assert server_apps.app_detail("tinyshop")["sync_error"] == ""


def test_watch_and_remove(tinyshop):
    connect(tinyshop)
    assert server_apps.watch("tiny-shop", server_apps.WatchBody(watch=True)) == {"watch": True}
    assert server_apps.app_detail("tiny-shop")["app"]["watch"] is True
    server_apps.remove_app("tiny-shop")
    assert server_apps.apps() == [] and (tinyshop[0] / "backend" / "app.py").is_file()


def test_an_analysis_streams_is_saved_and_shows_on_its_commit(tinyshop):
    repo, shas = tinyshop
    connect(tinyshop)
    body = server_apps.AnalyzeBody(old=shas["v1.2"], new=shas["v2.1-frontend-bug"])
    got = events(server_apps.analyze_app("tiny-shop", body))
    assert [e["node"] for e in got][-1] == "final" and got[-1]["final_report"]["decision"] == "BLOCK"
    saved = server_apps.saved_analysis("tiny-shop", shas["v1.2"], shas["v2.1-frontend-bug"])
    assert saved["layer_verdict"]["primary"] == "frontend"
    steps = saved["steps"]  # kept with the analysis, so the pipeline details also work for an old analysis
    assert [s["node"] for s in steps] == ["change_scan", "planner", "check_writing", "differential_run", "layer_attribution",
                                          "risk_assessment", "decision", "critic"]
    assert steps[0]["input"]["old"] == shas["v1.2"] or steps[0]["input"]["old"] == "v1.2"
    assert steps[6]["ai"][0]["task"] == "decision" and "layer_verdict" in steps[6]["input"] and steps[6]["output"]["decision"] == "BLOCK"
    commit = next(c for c in server_apps.app_detail("tiny-shop")["commits"] if c["sha"] == shas["v2.1-frontend-bug"])
    assert commit["analysis"]["decision"] == "BLOCK" and commit["analysis"]["layer"] == "frontend"


def test_only_one_analysis_runs_at_a_time(tinyshop):
    connect(tinyshop)
    assert server_apps._busy.acquire(blocking=False)
    try:
        got = events(server_apps.analyze_app("tiny-shop", server_apps.AnalyzeBody(old="v1.1", new="v1.2")))
    finally:
        server_apps._busy.release()
    assert [e["node"] for e in got] == ["error"] and "another app analysis is running" in got[0]["state_update"]["error"]
    assert server_apps._busy.acquire(blocking=False)  # the refused request did not take the lock
    server_apps._busy.release()


def test_bad_refs_are_refused_before_streaming(tinyshop):
    connect(tinyshop)
    for old, new, text in [("v1.1", "nope", "unknown ref"), ("--upload-pack=x", "v1.2", "invalid ref"), ("v1.2", "main", "same commit")]:
        with pytest.raises(ProjectError, match=text) as err:
            server_apps.analyze_app("tiny-shop", server_apps.AnalyzeBody(old=old, new=new))
        assert err.value.status == 400


def test_a_saved_analysis_that_does_not_exist_is_a_404(tinyshop):
    connect(tinyshop)
    with pytest.raises(ProjectError) as err:
        server_apps.saved_analysis("tiny-shop", "a" * 40, "b" * 40)
    assert err.value.status == 404


def test_over_http_the_routes_exist_and_analyze_needs_the_ui_header(tinyshop):
    from fastapi.testclient import TestClient
    client = TestClient(server.app, base_url="http://localhost")  # the server only accepts local host names
    assert {"/apps", "/apps/{app_id}", "/apps/{app_id}/analyze", "/apps/{app_id}/watch"} <= set(client.get("/openapi.json").json()["paths"])
    assert client.post("/apps", json={"name": "Tiny", "repo_path": str(tinyshop[0])}).status_code == 201
    assert client.get("/apps").json()[0]["id"] == "tiny"
    refused = client.post("/apps/tiny/analyze", json={"old": "v1.1", "new": "v1.2"})
    assert refused.status_code == 403 and "X-DeploySure" in refused.json()["detail"]
    assert client.post("/apps/tiny/analyze", json={"old": "v1.1", "new": "nope"}, headers={"X-DeploySure": "1"}).status_code == 400
    assert client.get("/apps/missing").status_code == 404
    assert client.get("/").status_code == 200  # the UI is still served after the routers
    assert client.get("/app-mode.js").headers["cache-control"] == "no-cache"  # a stale script once made a new button do nothing


def test_browse_lists_sorted_folders_hides_dot_folders_and_marks_a_repo(tmp_path):
    for name in ("b", "A", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("x")
    (tmp_path / "A" / ".git").mkdir()
    listing = server_apps.browse_folders(str(tmp_path))
    assert [f["name"] for f in listing["folders"]] == ["A", "b"] and listing["parent"] == str(tmp_path.parent) and listing["is_repo"] is False
    assert server_apps.browse_folders(str(tmp_path / "A"))["is_repo"] is True


def test_browse_with_no_path_lists_the_drives_and_home():
    listing = server_apps.browse_folders()
    assert listing["path"] == "" and listing["parent"] is None and str(Path.home()) in [f["path"] for f in listing["folders"]]


def test_browse_a_missing_folder_is_a_400_and_needs_the_ui_header(tmp_path):
    with pytest.raises(ProjectError) as err:
        server_apps.browse_folders(str(tmp_path / "nope"))
    assert err.value.status == 400
    from fastapi.testclient import TestClient
    assert TestClient(server.app, base_url="http://localhost").get("/browse-folders").status_code == 403


# ---------- example repos and the simulated developer commit ----------

from deploysure.demo_apps import build_tinyshop


@pytest.fixture
def demo_root(tmp_path, monkeypatch):
    root = tmp_path / "demo_apps"
    root.mkdir()
    monkeypatch.setattr(server_apps, "DEMO_APPS", root)
    return root


def test_the_examples_list_only_the_demo_repos_that_exist(demo_root):
    assert server_apps.examples() == []
    build_tinyshop.build_live(demo_root / "tinyshop_live")
    found = server_apps.examples()
    assert [e["path"] for e in found] == [str(demo_root / "tinyshop_live")] and "live" in found[0]["name"].lower() and found[0]["note"]


def test_a_simulated_commit_lands_in_the_demo_repo_and_shows_in_the_timeline(demo_root):
    live = demo_root / "tinyshop_live"
    build_tinyshop.build_live(live)
    server_apps.new_app(server_apps.NewApp(name="Live", repo_path=str(live)))
    assert len(server_apps.app_detail("live")["commits"]) == 3
    done = server_apps.demo_commit("live", server_apps.DemoCommit(change="frontend-bug"))
    detail = server_apps.app_detail("live")
    assert len(detail["commits"]) == 4 and detail["commits"][0]["sha"] == done["sha"] and "shorter products route" in done["message"]


def test_a_simulated_commit_is_refused_for_any_repo_outside_the_demo_folder(demo_root, tinyshop):
    server_apps.new_app(server_apps.NewApp(name="Mine", repo_path=str(tinyshop[0])))  # not inside demo_root
    before = len(server_apps.app_detail("mine")["commits"])
    with pytest.raises(ProjectError) as err:
        server_apps.demo_commit("mine", server_apps.DemoCommit(change="backend-bug"))
    assert err.value.status == 403 and len(server_apps.app_detail("mine")["commits"]) == before


def test_a_simulated_commit_needs_a_known_change_that_still_applies(demo_root):
    live = demo_root / "tinyshop_live"
    build_tinyshop.build_live(live)
    server_apps.new_app(server_apps.NewApp(name="Live", repo_path=str(live)))
    with pytest.raises(ProjectError, match="unknown change") as err:
        server_apps.demo_commit("live", server_apps.DemoCommit(change="nope"))
    assert err.value.status == 400
    server_apps.demo_commit("live", server_apps.DemoCommit(change="contract-break"))
    with pytest.raises(ProjectError, match="does not apply"):
        server_apps.demo_commit("live", server_apps.DemoCommit(change="contract-break"))


def test_the_app_detail_says_whether_it_is_a_demo_repo(demo_root, tinyshop):
    live = demo_root / "tinyshop_live"
    build_tinyshop.build_live(live)
    server_apps.new_app(server_apps.NewApp(name="Live", repo_path=str(live)))
    server_apps.new_app(server_apps.NewApp(name="Mine", repo_path=str(tinyshop[0])))
    assert server_apps.app_detail("live")["demo"] is True and server_apps.app_detail("mine")["demo"] is False
