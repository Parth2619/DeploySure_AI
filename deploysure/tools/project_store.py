"""Projects and their versions, stored as plain folders and JSON.

Every path is built from a checked project id or version name, never from raw user text.
"""
import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from deploysure.tools import code_reader
from deploysure.tools.code_reader import project_path, python_files

MAX_FILES = 200
MAX_BYTES = 200 * 1024
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,29}")
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
WINDOWS_RESERVED = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", re.IGNORECASE)
MAX_NAME = 80
MAX_NOTES = 5000

_locks: dict[tuple[str, str], threading.Lock] = {}


def analysis_lock(project_id: str, version: str) -> threading.Lock:
    """One analysis per version at a time: it rewrites generated test files in that version's folder."""
    return _locks.setdefault((project_id, version.lower()), threading.Lock())

DEFAULT_PYTEST_INI = """[pytest]
addopts = --import-mode=importlib -p no:cacheprovider
pythonpath = .
markers =
    critical: test covers a critical component
"""
DEFAULT_CONFTEST = """# Writes a critical flag into the junit XML so the runner reads status and criticality in one run.
def pytest_collection_modifyitems(items):
    for item in items:
        flag = item.get_closest_marker("critical") is not None
        item.user_properties.append(("critical", str(flag)))
"""


class ProjectError(ValueError):
    """A problem the user can fix. status is the HTTP code the server should use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    if not slug:
        raise ProjectError("project name needs at least one letter or number")
    return slug


def check_version_name(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ProjectError("version name must be 1 to 30 characters: letters, numbers, dot, dash or underscore, starting with a letter or number")
    # Windows silently drops a trailing dot and reserves some names, so the folder would not match the name.
    if version.endswith(".") or WINDOWS_RESERVED.fullmatch(version):
        raise ProjectError(f"{version!r} cannot be used as a version name on Windows. Try v1.0 or release-2.")


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_json(path: Path, keys: tuple = ()) -> dict:
    """Reads a JSON file we wrote. A hand-edited or damaged file gives a clear error, not a crash."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in data]
    except (ValueError, OSError, TypeError) as err:
        raise ProjectError(f"{path.name} in {path.parent.name!r} is damaged ({err}). Fix or delete that file.", 500)
    if missing:
        raise ProjectError(f"{path.name} in {path.parent.name!r} is missing {', '.join(missing)}. Fix or delete that file.", 500)
    return data


def _is_source(path: Path) -> bool:
    return path.suffix == ".py" and not path.name.startswith("test_") and path.name != "conftest.py"


def copy_snapshot(src: str, dest: Path) -> None:
    """Copies top-level .py files and pytest.ini into dest, after checking the folder rules."""
    folder = Path(src.strip().strip("\"'")).expanduser()  # Explorer's "Copy as path" adds quotes
    if not folder.is_dir():
        raise ProjectError(f"folder not found: {src}")
    files = [p for p in folder.iterdir() if p.is_file() and (p.suffix == ".py" or p.name == "pytest.ini")]
    if len(files) > MAX_FILES:
        raise ProjectError(f"too many files: {len(files)} (limit {MAX_FILES})")
    for p in files:
        if p.stat().st_size > MAX_BYTES:
            raise ProjectError(f"{p.name} is larger than {MAX_BYTES // 1024} KB")
    if not any(_is_source(p) for p in files):
        raise ProjectError("the folder needs at least one code file (a .py file that is not a test)")
    dest.mkdir(parents=True)
    try:
        for p in files:
            shutil.copy2(p, dest / p.name)
        if not (dest / "pytest.ini").exists():
            (dest / "pytest.ini").write_text(DEFAULT_PYTEST_INI, encoding="utf-8")
        if not (dest / "conftest.py").exists():
            (dest / "conftest.py").write_text(DEFAULT_CONFTEST, encoding="utf-8")
    except OSError as err:
        shutil.rmtree(dest, ignore_errors=True)  # no half-built folder, so the user can simply retry
        raise ProjectError(f"could not copy the folder: {err}")


def _write_version(project_id: str, version: str, baseline: str | None, notes: str) -> dict:
    first_line = notes.strip().splitlines()[0][:80] if notes.strip() else version
    meta = {"version": version, "baseline": baseline, "title": first_line, "notes": notes.strip(),
            "created": datetime.now().isoformat()}
    _dump(project_path(project_id) / "versions" / version / "version.json", meta)
    return meta


def load_project(project_id: str) -> dict:
    if not ID_RE.fullmatch(project_id) or not (project_path(project_id) / "project.json").is_file():
        raise ProjectError(f"unknown project: {project_id}", 404)
    return read_json(project_path(project_id) / "project.json", ("id", "name", "critical_modules", "customer_facing"))


def require_writable(project_id: str) -> dict:
    """Loads the project and refuses changes to a protected one (the demo shop must always work)."""
    project = load_project(project_id)
    if project.get("protected"):
        raise ProjectError(f"{project['name']} is read-only so the demo always works. Add your own project instead.", 403)
    return project


def _tests_changed_at(project_id: str) -> float:
    """Latest change to the project's test cases or its own test files. Generated test_case_*.py do not count."""
    folder = project_path(project_id) / "tests"
    times = [folder.stat().st_mtime] + [p.stat().st_mtime for p in folder.glob("case_*.json")] if folder.is_dir() else []
    times += [p.stat().st_mtime for p in project_path(project_id).glob("versions/*/test_*.py")
              if not p.name.startswith("test_case_")]
    return max(times, default=0.0)


def list_versions(project_id: str) -> list[dict]:
    root = project_path(project_id) / "versions"
    versions = []
    for folder in root.iterdir() if root.is_dir() else []:
        if (folder / "version.json").is_file():
            meta = read_json(folder / "version.json", ("version", "baseline", "title", "notes", "created"))
            result = folder / "last_result.json"
            try:
                last = read_json(result) if result.is_file() else None
            except ProjectError:
                last = None  # a damaged result file only means "not analyzed yet"
            if last is not None:
                last["stale"] = result.stat().st_mtime < _tests_changed_at(project_id)  # test cases changed since the run
            versions.append({**meta, "last_result": last})
    return sorted(versions, key=lambda v: v["created"])


def project_modules(project_id: str) -> list[str]:
    versions = list_versions(project_id)
    if not versions:
        return []
    folder = code_reader.release_path(versions[-1]["version"], project_id)
    return sorted(p.stem for p in python_files(folder) if _is_source(p))


def _card(project_id: str) -> dict:
    project, versions = load_project(project_id), list_versions(project_id)
    return {"id": project_id, "name": project["name"], "version_count": len(versions),
            "latest_version": versions[-1]["version"] if versions else None,
            "last_result": versions[-1]["last_result"] if versions else None}


def _safe_card(project_id: str) -> dict:
    """One damaged project must not hide all the others."""
    try:
        return _card(project_id)
    except ProjectError as err:
        return {"id": project_id, "name": project_id, "version_count": 0, "latest_version": None,
                "last_result": None, "error": str(err)}


def create_project(name: str, folder_path: str, version: str = "v1.0", critical_modules=()) -> dict:
    if len(name.strip()) > MAX_NAME:
        raise ProjectError(f"project name can have at most {MAX_NAME} characters")
    project_id = slugify(name)
    check_version_name(version)
    modules = [m.strip().removesuffix(".py") for m in critical_modules if m.strip()]
    for m in modules:
        if not m.isidentifier():
            raise ProjectError(f"critical module {m!r} is not a valid module name")
    if project_path(project_id).exists():
        raise ProjectError(f"a project called {project_id!r} already exists", 409)
    try:
        copy_snapshot(folder_path, project_path(project_id) / "versions" / version)
        _dump(project_path(project_id) / "project.json", {"id": project_id, "name": name.strip(), "created": datetime.now().isoformat(),
                                                          "critical_modules": modules, "customer_facing": {}})
        _write_version(project_id, version, None, "")
    except (ProjectError, OSError):
        shutil.rmtree(project_path(project_id), ignore_errors=True)  # we created this folder, so nothing else lives in it
        raise
    return _card(project_id)


def add_version(project_id: str, version: str, folder_path: str, notes: str) -> dict:
    require_writable(project_id)
    check_version_name(version)
    if len(notes) > MAX_NOTES:
        raise ProjectError(f"release notes can have at most {MAX_NOTES} characters")
    versions = list_versions(project_id)
    if any(v["version"].lower() == version.lower() for v in versions):  # Windows folders ignore case
        raise ProjectError(f"version {version!r} already exists", 409)
    copy_snapshot(folder_path, project_path(project_id) / "versions" / version)
    return _write_version(project_id, version, versions[-1]["version"] if versions else None, notes)


def list_projects() -> list[dict]:
    root = code_reader.PROJECTS_ROOT
    ids = sorted(p.name for p in root.iterdir() if (p / "project.json").is_file()) if root.is_dir() else []
    return sorted((_safe_card(i) for i in ids), key=lambda c: c["name"].lower())


def get_project(project_id: str) -> dict:
    return {**load_project(project_id), "versions": list_versions(project_id), "modules": project_modules(project_id)}


def save_result(project_id: str, version: str, report: dict) -> None:
    result = {k: report[k] for k in ("decision", "risk_score", "risk_level", "retry_count")}
    _dump(code_reader.release_path(version, project_id) / "last_result.json", {**result, "at": datetime.now().isoformat(timespec="seconds")})
