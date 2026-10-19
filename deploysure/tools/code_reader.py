"""Finds release folders and reads source files."""
import json
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parents[1] / "demo_project"
RELEASES_DIR = Path(__file__).resolve().parents[1] / "releases"


def release_path(version: str) -> Path:
    path = DEMO_ROOT / version
    if not path.is_dir():
        raise FileNotFoundError(f"no such release folder: {path}")
    return path


def load_release(release_id: str) -> dict:
    """Release metadata (baseline, title, notes) from releases/release_v2_1.json."""
    path = RELEASES_DIR / f"release_{release_id.replace('.', '_')}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no metadata for release {release_id}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_source(path: Path) -> str:
    # Normalise line endings so Windows and Linux checkouts compare equal.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def python_files(release_dir: Path) -> list[Path]:
    return sorted(release_dir.glob("*.py"))
