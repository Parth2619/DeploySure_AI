"""Finds project and version folders and reads source files."""
from pathlib import Path

PROJECTS_ROOT = Path(__file__).resolve().parents[1] / "projects"
DEFAULT_PROJECT = "demo-shop"


def project_path(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id


def release_path(version: str, project: str = DEFAULT_PROJECT) -> Path:
    path = project_path(project) / "versions" / version
    if not path.is_dir():
        raise FileNotFoundError(f"no such version folder: {path}")
    return path


def load_release(version: str, project: str = DEFAULT_PROJECT) -> dict:
    """Version metadata (baseline, title, notes) from the version's version.json."""
    from deploysure.tools.project_store import read_json  # imported here because project_store imports this module

    path = release_path(version, project) / "version.json"
    if not path.is_file():
        raise FileNotFoundError(f"no metadata for version {version}: {path}")
    meta = read_json(path, ("version", "baseline", "title", "notes"))
    return {"release_id": meta["version"], "baseline": meta["baseline"], "title": meta["title"], "notes": meta["notes"]}


def read_source(path: Path) -> str:
    # Normalise line endings so Windows and Linux checkouts compare equal.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def python_files(release_dir: Path) -> list[Path]:
    return sorted(release_dir.glob("*.py"))
