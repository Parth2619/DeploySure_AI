import pytest

from deploysure.tools import git_tool as git
from deploysure.tools.git_tool import GitError


def test_list_commits_shows_every_branch_with_tags(tinyshop):
    repo, shas = tinyshop
    commits = git.list_commits(repo)
    assert len(commits) == 6
    by_tag = {tag: c for c in commits for tag in c["tags"]}
    assert by_tag["v1.2"]["subject"] == "Report the currency from the CURRENCY setting"
    assert by_tag["v2.2-contract-break"]["sha"] == shas["v2.2-contract-break"]
    assert all(len(c["sha"]) == 40 and c["date"] for c in commits)


def test_resolve_turns_a_ref_into_a_sha(tinyshop):
    repo, shas = tinyshop
    assert git.resolve(repo, "v1.2") == shas["v1.2"]
    assert git.resolve(repo, shas["v1.2"]) == shas["v1.2"]
    assert git.resolve(repo, "main") == shas["v1.2"]


@pytest.mark.parametrize("bad", ["nope", "--upload-pack=x", "-h", "v1.2..v1.0", "", "a b", "../x", "v1.2;rm", "x" * 101])
def test_resolve_rejects_unknown_or_unsafe_refs(tinyshop, bad):
    with pytest.raises(GitError):
        git.resolve(tinyshop[0], bad)


def test_changed_files_with_status(tinyshop):
    repo, _ = tinyshop
    assert git.changed_files(repo, "v1.1", "v1.2") == [{"path": ".env.example", "status": "M"}, {"path": "backend/app.py", "status": "M"}]
    assert git.changed_files(repo, "v1.2", "v1.2") == []


def test_list_files_and_read_file(tinyshop):
    repo, _ = tinyshop
    assert "frontend/app.js" in git.list_files(repo, "v1.0")
    assert "FastAPI" in git.read_file(repo, "v1.0", "backend/app.py")
    assert "CURRENCY" in git.read_file(repo, "v1.2", ".env.example")
    assert "CURRENCY" not in git.read_file(repo, "v1.0", ".env.example")


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", "backend/../../x", ".env", "config/.env.local", "x\\y.py", ""])
def test_read_file_refuses_unsafe_paths_and_secret_files(tinyshop, path):
    with pytest.raises(GitError):
        git.read_file(tinyshop[0], "v1.0", path)


def test_missing_file_is_an_error(tinyshop):
    with pytest.raises(GitError):
        git.read_file(tinyshop[0], "v1.0", "nope.py")


def test_read_file_is_capped(tinyshop):
    assert len(git.read_file(tinyshop[0], "v1.0", "backend/app.py", max_chars=50)) == 50


def test_secret_files_are_hidden_from_listings(tinyshop, tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git.git_run(repo, "init", "-b", "main")
    (repo / ".env").write_text("KEY=secret\n")
    (repo / ".env.example").write_text("KEY=\n")
    (repo / "a.py").write_text("x = 1\n")
    git.git_run(repo, "add", "-A", "-f")
    git.git_run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "x")
    assert git.list_files(repo, "HEAD") == [".env.example", "a.py"]
    git.git_run(repo, "mv", "a.py", "b.py")
    git.git_run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-am", "y")
    assert [f["path"] for f in git.changed_files(repo, "HEAD~1", "HEAD")] == ["a.py", "b.py"]


def test_diff_patch_shows_the_change_and_is_capped(tinyshop):
    repo, _ = tinyshop
    patch = git.diff_patch(repo, "v1.2", "v2.0-backend-bug", "backend/app.py")
    assert "-    return round(sum(prices[i.product_id] * i.quantity for i in items), 2)" in patch
    assert "+    return round(sum(prices[i.product_id] for i in items), 2)" in patch
    assert len(git.diff_patch(repo, "v1.2", "v2.0-backend-bug", "backend/app.py", max_chars=40)) == 40


@pytest.mark.parametrize("path,layer", [
    ("backend/app.py", "backend"), ("server/main.py", "backend"), ("frontend/app.js", "frontend"),
    ("frontend/style.css", "frontend"), ("web/index.html", "frontend"), ("src/App.tsx", "frontend"),
    ("tests/test_api.py", "tests"), ("backend/conftest.py", "tests"), ("src/App.test.js", "tests"),
    ("requirements.txt", "dependencies"), ("frontend/package.json", "dependencies"), ("pyproject.toml", "dependencies"),
    (".env.example", "config"), ("docker-compose.yml", "config"), ("Dockerfile", "config"), ("setup.cfg", "config"),
    ("README.md", "docs"), ("docs/guide.rst", "docs"), ("LICENSE", "other"),
])
def test_files_are_sorted_into_layers(path, layer):
    assert git.classify_layer(path) == layer


def test_a_commit_with_no_tag_or_branch_is_listed(tmp_path):
    """Found with a real GitHub repo: untagged commits end with an empty field, and \\x1f counts as whitespace for str.strip()."""
    for args in (["init", "-q", "-b", "main"], ["config", "user.name", "T"], ["config", "user.email", "t@example.com"]):
        git.git_run(tmp_path, *args)
    for n in (1, 2, 3):
        (tmp_path / "f.txt").write_text(str(n))
        git.git_run(tmp_path, "add", "-A")
        git.git_run(tmp_path, "commit", "-q", "-m", f"commit {n}")
    commits = git.list_commits(tmp_path)  # only the newest commit has a branch name, the other two have no refs at all
    assert [c["subject"] for c in commits] == ["commit 3", "commit 2", "commit 1"]
    assert commits[0]["branches"] == ["main"] and commits[1]["branches"] == [] and commits[2]["tags"] == []
    assert commits[2]["parent"] is None and commits[1]["parent"] == commits[2]["sha"]


def test_commits_know_their_first_parent(tinyshop):
    repo, shas = tinyshop
    parent = {c["sha"]: c["parent"] for c in git.list_commits(repo)}
    assert parent[shas["v1.1"]] == shas["v1.0"] and parent[shas["v2.2-contract-break"]] == shas["v1.2"]
    assert parent[shas["v1.0"]] is None
