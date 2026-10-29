"""Read-only git access for scanning a user's repo.

Only read commands are used (log, diff, show, ls-tree), so no git hook ever runs. Real .env files are never read or
listed: only .env.example, .env.sample and .env.template are visible. Refs and paths come from outside, so both are checked.
"""
import re
import subprocess
from pathlib import Path

MAX_FILE_CHARS = 200_000
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~^-]{0,99}")
PATH_RE = re.compile(r"[\w.@+ /-]+")
# .env and .env.local are secrets. .env.example, .env.sample and .env.template are safe to read.
SECRET_RE = re.compile(r"(^|/)\.env(\.(?!(example|sample|template)$)[^/]*)?$")

DEPENDENCY_FILES = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "pyproject.toml", "poetry.lock",
                    "pipfile", "pipfile.lock"}
CONFIG_EXTENSIONS = {".ini", ".cfg", ".toml", ".yaml", ".yml"}
CONFIG_NAMES = {"dockerfile", "docker-compose.yml", "makefile"}
FRONTEND_EXTENSIONS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
FRONTEND_FOLDERS = {"frontend", "client", "web", "public", "static"}
TEST_SUFFIXES = (".test.js", ".test.ts", ".test.jsx", ".test.tsx", ".spec.js", ".spec.ts")


class GitError(Exception):
    """A git command failed, or a ref or path was not acceptable."""


def git_run(repo: Path, *args: str, timeout: int = 30) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    if done.returncode != 0:
        raise GitError(done.stderr.strip() or f"git {args[0]} failed")
    return done.stdout


def resolve(repo: Path, ref: str) -> str:
    """The commit sha a tag, branch or sha points to."""
    if not REF_RE.fullmatch(ref) or ".." in ref:
        raise GitError(f"invalid ref: {ref!r}")
    try:
        return git_run(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
    except GitError:
        raise GitError(f"unknown ref: {ref}")


def _check_path(path: str) -> None:
    if not path or not PATH_RE.fullmatch(path) or path.startswith("/") or ".." in path.split("/"):
        raise GitError(f"invalid path: {path!r}")
    if SECRET_RE.search(path):
        raise GitError(f"{path} may hold secrets and is never read")


def list_commits(repo: Path, limit: int = 50) -> list[dict]:
    """Newest first, across all branches. Each commit has its tags and branch names."""
    out = git_run(repo, "log", "--all", "--date-order", f"-n{int(limit)}", "--format=%H%x1f%P%x1f%s%x1f%aI%x1f%D%x1e")
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\r\n")  # not .strip(): the separator \x1f counts as whitespace, and a commit with no tag or branch ends with one
        if not record:
            continue
        sha, parents, subject, date, refs = record.split("\x1f")
        names = [r.strip() for r in refs.split(",") if r.strip()]
        commits.append({"sha": sha, "parent": parents.split()[0] if parents else None, "subject": subject, "date": date,
                        "tags": [n[5:] for n in names if n.startswith("tag: ")],
                        "branches": [n.replace("HEAD -> ", "") for n in names if not n.startswith("tag: ") and n != "HEAD"]})
    return commits


def list_files(repo: Path, ref: str) -> list[str]:
    out = git_run(repo, "ls-tree", "-r", "--name-only", "-z", resolve(repo, ref))
    return [p for p in out.split("\0") if p and not SECRET_RE.search(p)]


def read_file(repo: Path, ref: str, path: str, max_chars: int = MAX_FILE_CHARS) -> str:
    _check_path(path)
    try:
        return git_run(repo, "show", f"{resolve(repo, ref)}:{path}")[:max_chars]
    except GitError:
        raise GitError(f"{path} does not exist at {ref}")


def changed_files(repo: Path, old: str, new: str) -> list[dict]:
    """Files that differ between two commits, with status A (added), M (modified) or D (deleted)."""
    out = git_run(repo, "diff", "--name-status", "--no-renames", "-z", resolve(repo, old), resolve(repo, new))
    tokens = [t for t in out.split("\0") if t]
    return [{"path": path, "status": status[0]} for status, path in zip(tokens[::2], tokens[1::2]) if not SECRET_RE.search(path)]


def diff_patch(repo: Path, old: str, new: str, path: str, max_chars: int = 6000) -> str:
    """The unified diff of one file, cut to a length the AI can take (the free tier is small)."""
    _check_path(path)
    return git_run(repo, "diff", "--no-color", "-U2", resolve(repo, old), resolve(repo, new), "--", path)[:max_chars]


def classify_layer(path: str) -> str:
    """Which part of an app a file belongs to. A heuristic from names and folders, checked in this order."""
    parts = path.split("/")
    low = parts[-1].lower()
    ext = Path(low).suffix
    if low in DEPENDENCY_FILES or (low.startswith("requirements") and ext == ".txt"):
        return "dependencies"
    if low.startswith(".env") or ext in CONFIG_EXTENSIONS or low in CONFIG_NAMES:
        return "config"
    if parts[0] in {"tests", "test", "__tests__"} or low.startswith("test_") or low == "conftest.py" or low.endswith(TEST_SUFFIXES):
        return "tests"
    if parts[0] == "docs" or ext in {".md", ".rst"}:
        return "docs"
    if parts[0] in FRONTEND_FOLDERS or ext in FRONTEND_EXTENSIONS:
        return "frontend"
    if ext == ".py" or parts[0] in {"backend", "server", "api"}:
        return "backend"
    return "other"
