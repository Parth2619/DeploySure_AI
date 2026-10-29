import socket
import sys

import httpx
import pytest

from deploysure.tools import app_runner, git_tool
from deploysure.tools.app_runner import AppStartError

ENV_APP = '''import os

from fastapi import FastAPI

app = FastAPI()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/env")
def env():
    return sorted(os.environ)
'''


def make_repo(tmp_path, files: dict, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    git_tool.git_run(repo, "init", "-b", "main")
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git_tool.git_run(repo, "add", "-A", "-f")
    git_tool.git_run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "x")
    return repo


def is_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_checkout_extracts_a_commit_without_touching_the_repo(tinyshop, tmp_path):
    repo, shas = tinyshop
    sha, root, work = app_runner.checkout(repo, "v1.2")
    try:
        assert sha == shas["v1.2"] and (root / "backend" / "app.py").is_file() and not (root / ".git").exists()
        assert "CURRENCY" in (root / ".env.example").read_text()
        assert git_tool.git_run(repo, "status", "--short").strip() == ""
    finally:
        app_runner.remove(work)


def test_the_start_command_is_found_from_the_code(tinyshop):
    _, root, work = app_runner.checkout(tinyshop[0], "v1.2")
    try:
        command = app_runner.detect_start_command(root, 9999)
        assert command[:3] == [sys.executable, "-m", "uvicorn"] and "backend.app:app" in command and "9999" in command
    finally:
        app_runner.remove(work)


def test_an_app_runs_serves_and_is_removed(tinyshop):
    with app_runner.running_app(tinyshop[0], "v1.2") as app:
        reply = httpx.get(app.base_url + "/api/products", timeout=5)
        assert reply.status_code == 200 and reply.json()[0]["name"] == "Notebook"
        assert is_listening(app.port) and app.process.poll() is None
        work = app.root.parent
    assert not is_listening(app.port) and app.process.poll() is not None and not work.exists()


def test_two_versions_run_side_by_side(tinyshop):
    with app_runner.running_apps(tinyshop[0], ["v1.2", "v2.2-contract-break"]) as (old, new):
        assert old.port != new.port
        assert "price" in httpx.get(old.base_url + "/api/products", timeout=5).json()[0]
        assert "unit_price" in httpx.get(new.base_url + "/api/products", timeout=5).json()[0]
    assert not is_listening(old.port) and not is_listening(new.port)


def test_the_sandbox_environment_carries_no_secrets_but_the_example_values(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws_secret")
    repo = make_repo(tmp_path, {"backend/app.py": ENV_APP, ".env.example": "CURRENCY=USD\n"})
    with app_runner.running_app(repo, "main") as app:
        names = httpx.get(app.base_url + "/api/env", timeout=5).json()
    assert "GROQ_API_KEY" not in names and "AWS_SECRET_ACCESS_KEY" not in names
    assert "CURRENCY" in names and "PORT" in names


def test_secret_files_are_not_checked_out(tmp_path):
    repo = make_repo(tmp_path, {"backend/app.py": ENV_APP, ".env": "SECRET=1\n", ".env.production": "T=1\n", ".env.example": "A=1\n"})
    _, root, work = app_runner.checkout(repo, "main")
    try:
        assert not (root / ".env").exists() and not (root / ".env.production").exists() and (root / ".env.example").exists()
    finally:
        app_runner.remove(work)


def test_a_crash_on_start_reports_the_log_and_cleans_up(tmp_path):
    repo = make_repo(tmp_path, {"backend/app.py": 'from fastapi import FastAPI\nraise RuntimeError("boom on import")\napp = FastAPI()\n'})
    with pytest.raises(AppStartError) as err:
        with app_runner.running_app(repo, "main", startup_timeout=15):
            pass
    assert "boom on import" in str(err.value)


def test_a_slow_start_times_out_and_the_process_is_killed(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "x"})
    with pytest.raises(AppStartError) as err:
        with app_runner.running_app(repo, "main", start_command=[sys.executable, "-c", "import time; time.sleep(60)"], startup_timeout=1):
            pass
    assert "did not answer within 1s" in str(err.value)


def test_an_explicit_command_gets_the_port(tmp_path):
    repo = make_repo(tmp_path, {"index.html": "<h1>hi</h1>"})
    command = [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"]
    with app_runner.running_app(repo, "main", start_command=command, health_path="/") as app:
        assert "hi" in httpx.get(app.base_url + "/", timeout=5).text


def test_no_app_found_is_a_clear_error(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "nothing to run"})
    with pytest.raises(AppStartError) as err:
        with app_runner.running_app(repo, "main"):
            pass
    assert "could not find a FastAPI or Flask app" in str(err.value)


def test_a_command_string_is_refused(tmp_path):
    repo = make_repo(tmp_path, {"a.txt": "x"})
    with pytest.raises(TypeError):
        with app_runner.running_app(repo, "main", start_command="python -m http.server {port}"):
            pass


def test_an_error_inside_the_block_still_stops_the_app(tinyshop):
    with pytest.raises(ValueError):
        with app_runner.running_app(tinyshop[0], "v1.2") as app:
            raise ValueError("test failure")
    assert not is_listening(app.port) and app.process.poll() is not None


def test_bad_refs_are_refused_before_anything_starts(tinyshop):
    with pytest.raises(git_tool.GitError):
        with app_runner.running_app(tinyshop[0], "--upload-pack=x"):
            pass


def test_a_syntax_error_is_named_instead_of_reporting_a_missing_app(tmp_path):
    repo = make_repo(tmp_path, {"backend/app.py": "from fastapi import FastAPI\napp = FastAPI(\n"})
    with pytest.raises(AppStartError) as err:
        with app_runner.running_app(repo, "main"):
            pass
    assert "backend/app.py has a syntax error on line" in str(err.value)
