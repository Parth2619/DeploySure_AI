from deploysure.tools import app_scan


def test_a_frontend_only_change(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.0", "v1.1")
    assert scan["layers"] == {"frontend": ["frontend/app.js", "frontend/style.css"]}
    assert scan["contract_issues"] == [] and scan["endpoint_changes"] == [] and scan["config_changes"] == []


def test_a_backend_and_config_change_shows_the_new_env_key_and_field(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.1", "v1.2")
    assert scan["layers"] == {"backend": ["backend/app.py"], "config": [".env.example"]}
    assert scan["config_changes"] == [{"file": ".env.example", "added": ["CURRENCY"], "removed": [], "changed": []}]
    assert scan["endpoint_changes"] == [{"endpoint": "POST /api/orders", "kind": "fields_added", "fields": ["currency"]}]
    assert scan["contract_issues"] == []


def test_config_values_are_never_reported(tinyshop):
    text = str(app_scan.scan_change(tinyshop[0], "v1.1", "v1.2"))
    assert "USD" not in text and "8000" not in text


def test_a_logic_bug_is_invisible_to_the_map(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert scan["layers"] == {"backend": ["backend/app.py"]}
    assert scan["contract_issues"] == [] and scan["endpoint_changes"] == []
    assert scan["changed_functions"] == {"backend/app.py": ["order_total"]}


def test_a_wrong_route_in_the_page_is_caught_statically(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v2.1-frontend-bug")
    assert scan["layers"] == {"frontend": ["frontend/app.js"]}
    assert scan["contract_issues"] == [{"kind": "unknown_endpoint", "call": "GET /api/product", "file": "frontend/app.js"}]


def test_a_renamed_field_breaks_the_contract(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert scan["layers"] == {"backend": ["backend/app.py"], "tests": ["tests/test_api.py"]}
    assert scan["contract_issues"] == [{"kind": "missing_field", "endpoint": "GET /api/products", "field": "price",
                                        "read_by": ["frontend/app.js"]}]
    assert {"endpoint": "GET /api/products", "kind": "fields_removed", "fields": ["price"]} in scan["endpoint_changes"]


def test_unchanged_range_is_empty(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v1.2")
    assert scan["layers"] == {} and scan["files"] == []


# ---------- pure functions ----------

def test_requirements_diff():
    old = "fastapi==0.1\nuvicorn==1.0\n# a comment\n\npytest>=8\n"
    new = "fastapi==0.2\nhttpx==0.28\npytest>=8\n"
    assert app_scan.diff_requirements(old, new) == {
        "added": [{"name": "httpx", "version": "==0.28"}], "removed": [{"name": "uvicorn", "version": "==1.0"}],
        "changed": [{"name": "fastapi", "old": "==0.1", "new": "==0.2"}]}


def test_package_json_diff():
    old = '{"dependencies": {"react": "18.2.0"}, "devDependencies": {"vite": "5.0.0"}}'
    new = '{"dependencies": {"react": "18.3.0", "axios": "1.7.0"}}'
    assert app_scan.diff_package_json(old, new) == {
        "added": [{"name": "axios", "version": "1.7.0"}], "removed": [{"name": "vite", "version": "5.0.0"}],
        "changed": [{"name": "react", "old": "18.2.0", "new": "18.3.0"}]}


def test_broken_package_json_does_not_crash_the_scan():
    assert app_scan.diff_package_json("{ not json", "{}") == {"added": [], "removed": [], "changed": []}


def test_env_keys_diff_reports_keys_only():
    old = "PORT=8000\nSECRET_KEY=abc\n# note\n"
    new = "PORT=9000\nCURRENCY=USD\n"
    assert app_scan.diff_env_keys(old, new) == {"added": ["CURRENCY"], "removed": ["SECRET_KEY"], "changed": ["PORT"]}


# ---------- hostile and broken input ----------

import pytest

from deploysure.tools import git_tool


@pytest.fixture
def clone(tinyshop, tmp_path):
    repo = tmp_path / "clone"
    git_tool.git_run(tinyshop[0].parent, "clone", "--quiet", str(tinyshop[0]), str(repo))
    return repo


def commit(repo, files: dict, message="change"):
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git_tool.git_run(repo, "add", "-A", "-f")
    git_tool.git_run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)
    return git_tool.git_run(repo, "rev-parse", "HEAD").strip()


def test_a_commit_with_a_syntax_error_is_still_scannable(clone):
    new = commit(clone, {"backend/app.py": "def broken(:\n    pass\n"})
    scan = app_scan.scan_change(clone, "v1.2", new)
    assert scan["layers"] == {"backend": ["backend/app.py"]}
    assert scan["changed_functions"] == {"backend/app.py": ["<syntax error>"]}
    assert "backend/app.py has a syntax error on line 1" in scan["map_errors"][0]
    # Code that cannot be parsed has no readable endpoints, so claiming they were removed or that the page lost its API would be noise.
    assert scan["contract_issues"] == [] and scan["endpoint_changes"] == []


def test_unknown_or_unsafe_refs_are_errors(tinyshop):
    for bad in ("nope", "--upload-pack=x", "v1.2..v1.0"):
        with pytest.raises(git_tool.GitError):
            app_scan.scan_change(tinyshop[0], "v1.2", bad)


def test_a_committed_dot_env_is_never_reported(clone):
    new = commit(clone, {".env": "SECRET_KEY=hunter2\n", ".env.production": "TOKEN=abc\n", "backend/app.py": "# touched\n" + git_tool.read_file(clone, "v1.2", "backend/app.py")})
    scan = app_scan.scan_change(clone, "v1.2", new)
    text = str(scan)
    assert "hunter2" not in text and "SECRET_KEY" not in text and "TOKEN" not in text and ".env.production" not in text
    assert scan["layers"] == {"backend": ["backend/app.py"]}


def test_added_and_deleted_files_are_scanned(clone):
    new = commit(clone, {"requirements.txt": "fastapi==0.143.2\nuvicorn==0.54.0\nrequests==2.32.0\n", "frontend/extra.js": "fetch('/api/health')\n"})
    scan = app_scan.scan_change(clone, "v1.2", new)
    assert scan["dependency_changes"] == [{"file": "requirements.txt", "added": [{"name": "requests", "version": "==2.32.0"}],
                                           "removed": [{"name": "httpx", "version": "==0.28.1"}, {"name": "pytest", "version": "==9.1.1"}], "changed": []}]
    assert scan["files"][-1]["status"] in {"A", "M"} and any(f["status"] == "A" and f["path"] == "frontend/extra.js" for f in scan["files"])
