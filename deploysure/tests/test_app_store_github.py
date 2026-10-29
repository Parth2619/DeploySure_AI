"""Apps that come from a GitHub link. The tests use a local repo as the "GitHub" side, so they never touch the internet."""
import subprocess

import pytest

from deploysure.demo_apps import build_tinyshop
from deploysure.tools import app_store, git_tool
from deploysure.tools.project_store import ProjectError


@pytest.fixture
def remote(tmp_path, tinyshop, monkeypatch):
    """A private copy of the demo repo that plays GitHub, and a store that downloads from it."""
    copy = tmp_path / "remote"
    git_tool.git_run(tmp_path, "clone", "--quiet", str(tinyshop[0]), str(copy))
    monkeypatch.setattr(app_store, "APPS_ROOT", tmp_path / "apps")
    monkeypatch.setattr(app_store, "clone_source", lambda link: str(copy))
    monkeypatch.setattr(app_store, "_sync_state", {})
    return copy


@pytest.mark.parametrize("text, name", [
    ("https://github.com/Parth2619/priceright-demo", "priceright-demo"),
    ("https://github.com/Parth2619/priceright-demo.git", "priceright-demo"),
    ("  github.com/octocat/Hello-World/  ", "Hello-World"),
    ("https://www.github.com/a/b.c", "b.c"),
])
def test_a_github_link_is_accepted_and_made_canonical(text, name):
    repo, link = app_store.parse_github_url(text)
    assert repo == name and link == f"https://github.com/{text.strip().split('github.com/')[1].strip('/').removesuffix('.git')}.git"


@pytest.mark.parametrize("text", [
    "", "https://github.com/only-owner", "http://github.com/a/b", "https://gitlab.com/a/b", "https://evil.com/github.com/a/b",
    "https://user:token@github.com/a/b", "git@github.com:a/b.git", "file:///etc/passwd", "ssh://github.com/a/b", "--upload-pack=x",
    "https://github.com/a/b/tree/main", "https://github.com/../b", "https://github.com/a/.hidden", "https://github.com/a/b;rm -rf /",
    "ext::sh -c 'echo x'", "https://github.com/a/b c",
])
def test_anything_that_is_not_a_plain_github_repository_link_is_refused(text):
    with pytest.raises(ProjectError, match="https://github.com/owner/repo"):
        app_store.parse_github_url(text)


def test_connecting_a_github_link_downloads_a_copy_and_registers_it(remote):
    card = app_store.connect_github("", "https://github.com/someone/tinyshop")
    assert card["id"] == "tinyshop" and card["name"] == "tinyshop"
    detail = app_store.get_app("tinyshop")
    assert detail["app"]["source"] == "github" and detail["app"]["url"] == "https://github.com/someone/tinyshop"
    assert detail["app"]["repo_path"].startswith(str(app_store.APPS_ROOT.resolve())) and detail["sync_error"] == ""
    assert len(git_tool.list_commits(app_store.APPS_ROOT / "tinyshop" / "repo")) >= 3
    assert git_tool.git_run(remote, "status", "--short").strip() == ""  # the original is untouched


def test_new_commits_on_github_show_up_without_pulling(remote):
    app_store.connect_github("Live", "https://github.com/someone/tinyshop")
    before = {c["sha"] for c in app_store.get_app("live")["commits"]}
    sha = build_tinyshop.push_commit(remote, "safe-copy")
    assert app_store.sync_app("live", force=True) == ""  # the page does this by itself every few seconds
    after = app_store.get_app("live")["commits"]
    new = [c for c in after if c["sha"] not in before]
    assert [c["sha"] for c in new] == [sha] and new[0]["parent"] in before


def test_github_is_not_asked_more_often_than_every_few_seconds(remote, monkeypatch):
    app_store.connect_github("Live", "https://github.com/someone/tinyshop")
    calls = []
    monkeypatch.setattr(app_store, "_git_network", lambda args, what, timeout: calls.append(args))
    app_store.sync_app("live", force=True)
    for _ in range(5):
        app_store.get_app("live")
    assert len(calls) == 1


def test_a_github_problem_is_reported_not_raised(remote, monkeypatch):
    app_store.connect_github("Live", "https://github.com/someone/tinyshop")

    def down(args, what, timeout):
        raise ProjectError("checking GitHub failed: could not resolve host.")
    monkeypatch.setattr(app_store, "_git_network", down)
    assert "could not resolve host" in app_store.sync_app("live", force=True)
    detail = app_store.get_app("live")
    assert "could not resolve host" in detail["sync_error"] and len(detail["commits"]) >= 3  # the saved copy still works


def test_a_failed_download_leaves_nothing_behind(remote, monkeypatch):
    monkeypatch.setattr(app_store, "clone_source", lambda link: str(remote / "does-not-exist"))
    with pytest.raises(ProjectError, match="downloading the repository failed"):
        app_store.connect_github("Broken", "https://github.com/someone/missing")
    assert app_store.list_apps() == [] and not (app_store.APPS_ROOT / "broken").exists()


def test_a_slow_or_private_repository_gives_a_clear_message(remote, monkeypatch):
    def timed_out(*a, **k):
        raise subprocess.TimeoutExpired("git", 1)
    monkeypatch.setattr(app_store.subprocess, "run", timed_out)
    with pytest.raises(ProjectError, match="took longer") as err:
        app_store.connect_github("Slow", "https://github.com/someone/slow")
    assert err.value.status == 504

    class Done:
        returncode, stdout = 128, ""
        stderr = "remote: Repository not found.\nfatal: repository 'https://github.com/someone/private/' not found"
    monkeypatch.setattr(app_store.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(ProjectError, match="private"):
        app_store.connect_github("Secret", "https://github.com/someone/private")
    assert app_store.list_apps() == []


def test_the_same_name_conflicts_before_anything_is_downloaded(remote, monkeypatch):
    app_store.connect_github("Live", "https://github.com/someone/tinyshop")
    monkeypatch.setattr(app_store, "_git_network", lambda *a, **k: pytest.fail("must not download again"))
    with pytest.raises(ProjectError) as err:
        app_store.connect_github("live", "https://github.com/someone/other")
    assert err.value.status == 409


def test_removing_a_github_app_deletes_its_downloaded_copy_but_not_the_original(remote):
    app_store.connect_github("Live", "https://github.com/someone/tinyshop")
    folder = app_store.APPS_ROOT / "live"
    assert (folder / "repo" / ".git").is_dir()
    app_store.delete_app("live")
    assert not folder.exists() and (remote / "backend" / "app.py").is_file()
