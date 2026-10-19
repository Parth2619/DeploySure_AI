"""The entry points the UI calls. Keep these two signatures stable.

    from deploysure.api import run_release_validation, stream_release_validation
"""
import re
from datetime import datetime
from typing import Iterator

from deploysure.orchestration.graph import build_graph, initial_state
from deploysure.tools.code_reader import RELEASES_DIR, load_release

REPORT_KEYS = ("release_id", "changed_files", "impacted_modules", "selected_tests", "test_results", "risk_score",
               "risk_level", "decision", "decision_reason", "critic_result", "critic_reason", "retry_count", "trace")
# Hard stop behind the Critic's own retry cap, in case the routing is ever broken.
RECURSION_LIMIT = 60


def check_release(release_id: str) -> None:
    """Raises ValueError or FileNotFoundError. The id comes from outside, so it is checked before any path use."""
    if not re.fullmatch(r"[\w.]+", release_id):
        raise ValueError(f"invalid release id: {release_id!r}")
    load_release(release_id)


def list_releases() -> list[dict]:
    releases = (load_release(p.stem.removeprefix("release_").replace("_", ".")) for p in sorted(RELEASES_DIR.glob("release_*.json")))
    return [{"release_id": r["release_id"], "baseline": r["baseline"], "title": r["title"]} for r in releases]


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def stream_release_validation(release_id: str) -> Iterator[dict]:
    """Yields one event as each node finishes, then a final event carrying final_report."""
    check_release(release_id)
    state = dict(initial_state(release_id))
    config = {"recursion_limit": RECURSION_LIMIT}
    for chunk in build_graph().stream(initial_state(release_id), stream_mode="updates", config=config):
        for node, update in chunk.items():
            state.update({k: v for k, v in update.items() if k != "trace"})
            state["trace"] = state["trace"] + update.get("trace", [])
            yield {"node": node, "status": "done", "state_update": update, "timestamp": _now()}
    yield {"node": "final", "status": "done", "state_update": {}, "timestamp": _now(),
           "final_report": {key: state[key] for key in REPORT_KEYS}}


def run_release_validation(release_id: str) -> dict:
    """Runs the whole workflow and returns final_report."""
    for event in stream_release_validation(release_id):
        if event["node"] == "final":
            return event["final_report"]
    raise RuntimeError("workflow ended without a final event")
