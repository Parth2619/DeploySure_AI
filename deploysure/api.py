"""The entry points the UI calls. Keep these two signatures stable.

    from deploysure.api import run_release_validation, stream_release_validation
"""
from datetime import datetime
from typing import Iterator

from deploysure.orchestration.graph import build_graph, initial_state
from deploysure.tools.code_reader import DEFAULT_PROJECT, load_release
from deploysure.tools.project_store import ProjectError, analysis_lock, check_version_name, load_project, save_result

REPORT_KEYS = ("release_id", "changed_files", "impacted_modules", "selected_tests", "test_results", "risk_score",
               "risk_level", "decision", "decision_reason", "critic_result", "critic_reason", "retry_count", "trace")
# Hard stop behind the Critic's own retry cap, in case the routing is ever broken.
RECURSION_LIMIT = 60


def check_release(release_id: str, project_id: str = DEFAULT_PROJECT) -> None:
    """Raises ProjectError (a ValueError). The ids come from outside, so they are checked before any path use."""
    load_project(project_id)
    check_version_name(release_id)
    try:
        meta = load_release(release_id, project_id)
    except FileNotFoundError:
        raise ProjectError(f"unknown version: {release_id}", 404)
    if meta["baseline"] is None:
        raise ProjectError(f"{release_id} is the first version, so there is nothing to compare it with")


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def stream_release_validation(release_id: str, project_id: str = DEFAULT_PROJECT) -> Iterator[dict]:
    """Yields one event as each node finishes, then a final event carrying final_report."""
    check_release(release_id, project_id)
    lock = analysis_lock(project_id, release_id)
    if not lock.acquire(blocking=False):
        raise ProjectError(f"{release_id} is already being analyzed. Wait for it to finish.", 409)
    try:
        state = dict(initial_state(release_id, project_id))
        config = {"recursion_limit": RECURSION_LIMIT}
        for chunk in build_graph().stream(initial_state(release_id, project_id), stream_mode="updates", config=config):
            for node, update in chunk.items():
                state.update({k: v for k, v in update.items() if k != "trace"})
                state["trace"] = state["trace"] + update.get("trace", [])
                yield {"node": node, "status": "done", "state_update": update, "timestamp": _now()}
        report = {key: state[key] for key in REPORT_KEYS}
        save_result(project_id, release_id, report)  # the project cards show the latest verdict
        yield {"node": "final", "status": "done", "state_update": {}, "timestamp": _now(), "final_report": report}
    finally:
        lock.release()


def run_release_validation(release_id: str, project_id: str = DEFAULT_PROJECT) -> dict:
    """Runs the whole workflow and returns final_report."""
    for event in stream_release_validation(release_id, project_id):
        if event["node"] == "final":
            return event["final_report"]
    raise RuntimeError("workflow ended without a final event")
