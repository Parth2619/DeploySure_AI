"""Runs one commit of an app in a throwaway folder, on a free port, with a locked-down environment.

- The commit is exported with git archive, so the user's working tree is never touched. Secret files (.env, .env.local)
  are not exported.
- The app gets only a short allowlist of environment variables plus the values from .env.example. Our own secrets,
  such as the Groq key, never reach it.
- It always stops the process (and its children) and deletes the folder, even when something fails.
- The app runs with this Python and the packages installed here. It does not install the app's own dependencies.
- Running an app runs its code, exactly like running its tests. Use dummy projects only, on a local machine.
"""
import ast
import contextlib
import io
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Iterator, NamedTuple

import httpx

from deploysure.tools import git_tool
from deploysure.tools.app_scan import env_pairs

ENV_ALLOWLIST = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
                 "LANG", "LC_ALL")
SKIP_FOLDERS = {"node_modules", "venv", ".venv", "tests", "test", "__pycache__", "site-packages"}
LOG_TAIL = 1500


class AppStartError(Exception):
    """The app could not be found, did not start, or did not answer in time. The message ends with the app's log."""


class RunningApp(NamedTuple):
    ref: str
    sha: str
    root: Path
    base_url: str
    port: int
    process: subprocess.Popen
    log_path: Path


def remove(work: Path) -> None:
    for _ in range(10):  # on Windows a just-killed process can hold a file for a moment
        try:
            shutil.rmtree(work)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.3)
    shutil.rmtree(work, ignore_errors=True)


def checkout(repo: Path, ref: str) -> tuple[str, Path, Path]:
    """Exports a commit into a new temp folder. Returns (sha, app folder, work folder to delete afterwards)."""
    sha = git_tool.resolve(repo, ref)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha], capture_output=True, timeout=60)
    if archive.returncode != 0:
        raise git_tool.GitError(archive.stderr.decode("utf-8", "replace").strip() or "git archive failed")
    work = Path(tempfile.mkdtemp(prefix="deploysure-app-"))
    root = work / "app"
    root.mkdir()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            members = [m for m in tar.getmembers() if not git_tool.SECRET_RE.search(m.name)]
            tar.extractall(root, members=members, filter="data")  # the data filter refuses paths that escape root
    except BaseException:
        remove(work)
        raise
    return sha, root, work


def detect_start_command(root: Path, port: int) -> list[str]:
    """The command to start a FastAPI or Flask app, found by looking for the line that creates it."""
    broken = None
    for path in sorted(root.rglob("*.py"), key=lambda p: (len(p.relative_to(root).parts), str(p))):
        relative = path.relative_to(root)
        if any(part in SKIP_FOLDERS or part.startswith(".") for part in relative.parts[:-1]):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as err:
            broken = broken or f"{relative.as_posix()} has a syntax error on line {err.lineno}: {err.msg}"
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id in {"FastAPI", "Flask"} and isinstance(node.targets[0], ast.Name)):
                parts = list(relative.with_suffix("").parts)
                module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
                target = f"{module}:{node.targets[0].id}"
                if node.value.func.id == "FastAPI":
                    return [sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
                return [sys.executable, "-m", "flask", "--app", target, "run", "--host", "127.0.0.1", "--port", str(port)]
    if broken:  # the app is probably in the file that cannot be read, so say that instead of "not found"
        raise AppStartError(broken)
    raise AppStartError("could not find a FastAPI or Flask app. Pass start_command, for example "
                        "[python, '-m', 'uvicorn', 'backend.app:app', '--port', '{port}'].")


def sandbox_env(root: Path, port: int) -> dict[str, str]:
    """Example values from .env.example, then a short allowlist of ours. Nothing else is passed on."""
    example = root / ".env.example"
    env = env_pairs(example.read_text(encoding="utf-8", errors="replace")) if example.is_file() else {}
    env.update({k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ})
    env.update({"PORT": str(port), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
    return env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stop(process: subprocess.Popen) -> None:
    """Stops the process and anything it started."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=15)
        else:
            import signal
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _log_tail(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL:].strip() if path.is_file() else ""


def _wait_until_up(process: subprocess.Popen, url: str, timeout: int, log_path: Path) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AppStartError(f"the app exited with code {process.returncode} before it was ready.\n{_log_tail(log_path)}")
        try:
            if httpx.get(url, timeout=1).status_code < 500:  # any answer below 500 means the server is up
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AppStartError(f"the app did not answer within {timeout}s at {url}.\n{_log_tail(log_path)}")


def start_app(repo: Path, ref: str, start_command: list[str] | None = None, health_path: str = "/api/health",
              startup_timeout: int = 30) -> RunningApp:
    if start_command is not None and not isinstance(start_command, (list, tuple)):
        raise TypeError("start_command must be a list of arguments, not a string")
    sha, root, work = checkout(repo, ref)
    process = None
    try:
        port = free_port()
        command = detect_start_command(root, port) if start_command is None else [str(a).replace("{port}", str(port)) for a in start_command]
        log_path = work / "app.log"
        flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with open(log_path, "wb") as log:
            process = subprocess.Popen(command, cwd=root, env=sandbox_env(root, port), stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, **flags)
        base_url = f"http://127.0.0.1:{port}"
        _wait_until_up(process, base_url + health_path, startup_timeout, log_path)
        return RunningApp(ref, sha, root, base_url, port, process, log_path)
    except BaseException:
        if process is not None:
            stop(process)
        remove(work)
        raise


@contextlib.contextmanager
def running_app(repo: Path, ref: str, **options) -> Iterator[RunningApp]:
    """Starts a commit, hands it over, and always stops and deletes it afterwards."""
    app = start_app(repo, ref, **options)
    try:
        yield app
    finally:
        stop(app.process)
        remove(app.root.parent)


@contextlib.contextmanager
def running_apps(repo: Path, refs: list[str], **options) -> Iterator[tuple[RunningApp, ...]]:
    """Several commits at the same time, each on its own port, for example the old and the new version."""
    with contextlib.ExitStack() as stack:
        yield tuple(stack.enter_context(running_app(repo, ref, **options)) for ref in refs)
