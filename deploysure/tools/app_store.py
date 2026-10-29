"""Connected apps (git repos) and their saved analyses, as plain folders and JSON, like projects.

    apps/<app_id>/app.json                              name, repo_path, created, watch
    apps/<app_id>/analyses/<old12>_<new12>.json         the final report of one analysis

Connecting an app only remembers where the repo is. DeploySure never writes into the repo, and removing an app never
touches it.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from deploysure.tools import git_tool
from deploysure.tools.project_store import ID_RE, ProjectError, read_json, slugify

APPS_ROOT = Path(__file__).resolve().parents[1] / "apps"
MAX_NAME = 80
MAX_COMMITS = 100
SHA_RE = re.compile(r"[0-9a-f]{12,40}")
# Only plain github.com repository links are accepted: no other host, no login in the link, no other git transport.
GITHUB_RE = re.compile(r"(?:https://)?(?:www\.)?github\.com/([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})/([A-Za-z0-9_][A-Za-z0-9_.-]{0,99}?)(?:\.git)?/?")
CLONE_TIMEOUT = 180
FETCH_TIMEOUT = 60
SYNC_EVERY = 10  # seconds between GitHub checks for one app, however often the page asks
_sync_state: dict[str, tuple[float, str]] = {}  # app id -> (time of the last check, its error text)
_sync_lock = threading.Lock()


def _dir(app_id: str) -> Path:
    if not ID_RE.fullmatch(app_id):
        raise ProjectError(f"unknown app: {app_id}", 404)
    return APPS_ROOT / app_id


def _load(app_id: str) -> dict:
    path = _dir(app_id) / "app.json"
    if not path.is_file():
        raise ProjectError(f"unknown app: {app_id}", 404)
    return read_json(path, ("id", "name", "repo_path", "created", "watch"))


def _commits(app: dict, limit: int) -> list[dict]:
    """The app's commits. A repo that was moved, deleted or damaged gives one clear error."""
    repo = Path(app["repo_path"])
    try:
        if repo.is_dir():
            return git_tool.list_commits(repo, limit)
    except git_tool.GitError:
        pass
    raise ProjectError(f"the repo at {repo} no longer exists or is not a git repository. Remove this app and connect it again.", 404)


def _analysis_path(app_id: str, old_sha: str, new_sha: str) -> Path:
    if not (SHA_RE.fullmatch(old_sha) and SHA_RE.fullmatch(new_sha)):
        raise ProjectError("invalid commit id")
    return _dir(app_id) / "analyses" / f"{old_sha[:12]}_{new_sha[:12]}.json"


def connect_app(name: str, repo_path: str) -> dict:
    if len(name.strip()) > MAX_NAME:
        raise ProjectError(f"app name can have at most {MAX_NAME} characters")
    app_id = slugify(name)
    path = Path(repo_path.strip().strip("\"'")).expanduser()
    if not path.is_dir():
        raise ProjectError(f"the folder {path} does not exist")
    try:
        git_tool.git_run(path, "rev-parse", "--git-dir")
    except git_tool.GitError:
        raise ProjectError(f"{path} is not a git repository")
    try:
        has_commits = bool(git_tool.list_commits(path, 1))
    except git_tool.GitError:  # an empty repo makes git log fail
        has_commits = False
    if not has_commits:
        raise ProjectError(f"{path} has no commits yet")
    if _dir(app_id).exists():
        raise ProjectError(f"an app called {app_id!r} is already connected", 409)
    _dir(app_id).mkdir(parents=True)
    (_dir(app_id) / "app.json").write_text(json.dumps(
        {"id": app_id, "name": name.strip(), "repo_path": str(path.resolve()), "created": datetime.now().isoformat(), "watch": False}, indent=2),
        encoding="utf-8")
    return _card(app_id)


def parse_github_url(text: str) -> tuple[str, str]:
    """(repo name, the link in its one accepted form) for a public GitHub repository link."""
    match = GITHUB_RE.fullmatch(text.strip())
    if not match:
        raise ProjectError("the link must look like https://github.com/owner/repo")
    owner, repo = match.groups()
    return repo, f"https://github.com/{owner}/{repo}.git"


def clone_source(url: str) -> str:
    return url  # a separate step so the tests can point it at a local repo instead of the internet


def _git_network(args: list[str], what: str, timeout: int) -> None:
    """Runs a git command that talks to GitHub. Never asks for a password: a private repo just fails."""
    try:
        done = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise ProjectError(f"{what} took longer than {timeout} seconds", 504)
    except OSError:
        raise ProjectError("git is not installed on this computer", 500)
    if done.returncode != 0:
        message = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "git failed"
        hint = " The repository was not found, or it is private. Only public GitHub repositories work." if re.search(r"not found|Authentication|could not read|Invalid username", done.stderr, re.I) else ""
        raise ProjectError(f"{what} failed: {message[:160]}.{hint}")


def _force_rmtree(path: Path) -> None:
    """rmtree that also removes read-only files (git packs are read-only on Windows)."""
    def fix(func, target, *_):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def connect_github(name: str, url: str) -> dict:
    """Downloads a public GitHub repository into our own apps folder and registers it. It is then kept up to date by sync_app."""
    repo_name, link = parse_github_url(url)
    name = name.strip() or repo_name
    if len(name) > MAX_NAME:
        raise ProjectError(f"app name can have at most {MAX_NAME} characters")
    app_id = slugify(name)
    if _dir(app_id).exists():
        raise ProjectError(f"an app called {app_id!r} is already connected", 409)
    _dir(app_id).mkdir(parents=True)
    try:
        dest = _dir(app_id) / "repo"
        # Only the default branch: the timeline then shows what lands on it, and the clone stays small.
        _git_network(["clone", "--quiet", "--single-branch", "--", clone_source(link), str(dest)], "downloading the repository", CLONE_TIMEOUT)
        if not git_tool.list_commits(dest, 1):
            raise ProjectError("that repository has no commits yet")
        (_dir(app_id) / "app.json").write_text(json.dumps(
            {"id": app_id, "name": name, "repo_path": str(dest.resolve()), "created": datetime.now().isoformat(), "watch": False,
             "source": "github", "url": link[:-4]}, indent=2), encoding="utf-8")
    except Exception:
        _force_rmtree(_dir(app_id))  # no half-made app is left behind
        raise
    return _card(app_id)


def sync_app(app_id: str, force: bool = False) -> str:
    """Fetches new commits for an app that came from GitHub. Returns the error text, or "". Checks GitHub at most every SYNC_EVERY seconds."""
    app = _load(app_id)
    if app.get("source") != "github":
        return ""
    last_time, last_error = _sync_state.get(app_id, (float("-inf"), ""))
    if not force and time.monotonic() - last_time < SYNC_EVERY:
        return last_error
    if not _sync_lock.acquire(blocking=False):  # another check is running, so this page just shows what is there
        return last_error
    try:
        error = ""
        try:
            _git_network(["-C", app["repo_path"], "fetch", "--quiet", "--prune", "origin"], "checking GitHub", FETCH_TIMEOUT)
        except ProjectError as err:
            error = str(err)
        _sync_state[app_id] = (time.monotonic(), error)
        return error
    finally:
        _sync_lock.release()


def _summary(report: dict, saved_at: float) -> dict:
    return {"decision": report["decision"], "risk_level": report["risk_level"], "risk_score": report["risk_score"],
            "layer": report["layer_verdict"]["primary"], "confidence": report["layer_verdict"]["confidence"],
            "at": datetime.fromtimestamp(saved_at).isoformat(timespec="seconds")}


def _card(app_id: str) -> dict:
    app = _load(app_id)
    commits = _commits(app, 1)
    count = len(list((_dir(app_id) / "analyses").glob("*.json"))) if (_dir(app_id) / "analyses").is_dir() else 0
    return {"id": app_id, "name": app["name"], "repo_path": app["repo_path"], "watch": app["watch"], "analyses": count,
            "latest": {"sha": commits[0]["sha"], "short": commits[0]["sha"][:7], "subject": commits[0]["subject"], "date": commits[0]["date"]}}


def list_apps() -> list[dict]:
    ids = sorted(p.name for p in APPS_ROOT.iterdir() if (p / "app.json").is_file()) if APPS_ROOT.is_dir() else []
    cards = []
    for app_id in ids:
        try:
            cards.append(_card(app_id))
        except ProjectError as err:  # one broken app must not hide the others
            cards.append({"id": app_id, "name": app_id, "repo_path": "", "watch": False, "analyses": 0, "latest": None, "error": str(err)})
    return sorted(cards, key=lambda c: c["name"].lower())


def get_app(app_id: str) -> dict:
    """The app and its commit timeline, newest first. A commit shows the saved analysis against its parent, if any."""
    app = _load(app_id)
    sync_error = sync_app(app_id)
    commits = []
    for c in _commits(app, MAX_COMMITS):
        saved = None
        if c["parent"]:
            path = _analysis_path(app_id, c["parent"], c["sha"])
            if path.is_file():
                saved = _summary(json.loads(path.read_text(encoding="utf-8")), path.stat().st_mtime)
        commits.append({**c, "short": c["sha"][:7], "analysis": saved})
    return {"app": app, "commits": commits, "sync_error": sync_error}


def save_analysis(app_id: str, report: dict) -> None:
    path = _analysis_path(app_id, report["old_sha"], report["new_sha"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def load_analysis(app_id: str, old_sha: str, new_sha: str) -> dict:
    path = _analysis_path(app_id, old_sha, new_sha)
    if not path.is_file():
        raise ProjectError("this comparison has not been analyzed yet", 404)
    return json.loads(path.read_text(encoding="utf-8"))


def set_watch(app_id: str, watch: bool) -> None:
    app = _load(app_id)
    (_dir(app_id) / "app.json").write_text(json.dumps({**app, "watch": bool(watch)}, indent=2), encoding="utf-8")


def delete_app(app_id: str) -> None:
    _load(app_id)
    _force_rmtree(_dir(app_id))  # only our own registry folder. A repo you pointed us to is never inside it, a GitHub copy is.
    _sync_state.pop(app_id, None)
