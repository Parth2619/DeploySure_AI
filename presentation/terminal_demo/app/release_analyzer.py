"""Stage 1: what is being released, and does it differ from the approved baseline?"""
import hashlib
from pathlib import Path

COMPONENT = "pricing"
APP_FILE = "demo_app/pricing.py"
BASELINE_FILE = "baseline/pricing.py"


def _text(path: Path) -> str | None:
    # Normalise line endings so a copy made on another system does not look like a change.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None


def analyze_release(root: Path) -> dict:
    root = Path(root)
    code, baseline = _text(root / APP_FILE), _text(root / BASELINE_FILE)
    digest = hashlib.sha256(code.encode()).hexdigest()[:8] if code is not None else "missing"
    modified = code is not None and baseline is not None and code != baseline
    state = "missing" if code is None else "differs from the approved baseline" if modified else "matches the approved baseline"
    return {
        "release_id": f"{COMPONENT}-{digest}",
        "components": [COMPONENT] if code is not None else [],
        "files": [APP_FILE],
        "missing": [APP_FILE] if code is None else [],
        "lines": len(code.splitlines()) if code else 0,
        "modified": modified,  # information only: a changed file is never blocked just for being changed
        "summary": f"{APP_FILE} {state}",
    }
