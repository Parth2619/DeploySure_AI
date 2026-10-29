"""Entry points for app mode: check a whole app (a git repo) by comparing two commits.

    from deploysure.app_api import run_app_validation, stream_app_validation
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

from deploysure.models import llm
from deploysure.orchestration.app_graph import build_app_graph, initial_app_state
from deploysure.tools import git_tool

# Hard stop behind the Critic's own retry cap, in case the routing is ever broken.
RECURSION_LIMIT = 60
APP_REPORT_KEYS = ("repo", "old", "new", "old_sha", "new_sha", "layers_changed", "contract_issues", "endpoint_changes",
                   "config_changes", "dependency_changes", "check_sources", "api_summary", "browser_summary", "api_results",
                   "browser_results", "start_error", "browser_error", "layer_verdict", "risk_score", "risk_level",
                   "risk_components", "decision", "decision_reason", "critic_result", "critic_reason", "retry_count", "trace")


class AppRequestError(ValueError):
    """The repo path or one of the refs is not usable. The message says what to fix."""


def check_app_request(repo: Path, old: str, new: str) -> None:
    repo = Path(repo)
    if not repo.is_dir():
        raise AppRequestError(f"the folder {repo} does not exist")
    try:
        git_tool.git_run(repo, "rev-parse", "--git-dir")
        shas = [git_tool.resolve(repo, ref) for ref in (old, new)]
    except git_tool.GitError as err:
        raise AppRequestError(f"{repo} is not a git repository" if "not a git repository" in str(err) else str(err))
    if shas[0] == shas[1]:
        raise AppRequestError(f"{old} and {new} are the same commit, so there is nothing to compare")


def _for_ui(update: dict) -> dict:
    """The scan carries both maps for the agents. The UI does not need them and they are large."""
    if "scan" in update:
        return {**update, "scan": {k: v for k, v in update["scan"].items() if k not in {"old_map", "new_map"}}}
    return update


def _report(state: dict) -> dict:
    scan = state["scan"]
    return {
        "repo": state["repo"], "old": state["old"], "new": state["new"], "old_sha": state["old_sha"], "new_sha": state["new_sha"],
        "layers_changed": scan["layers"], "contract_issues": scan["contract_issues"], "endpoint_changes": scan["endpoint_changes"],
        "config_changes": scan["config_changes"], "dependency_changes": scan["dependency_changes"],
        "check_sources": state["check_sources"], "api_summary": state["api_report"]["summary"],
        "browser_summary": state["browser_report"]["summary"], "api_results": state["api_report"]["results"],
        "browser_results": state["browser_report"]["results"], "start_error": state["start_error"], "browser_error": state["browser_error"],
        **{key: state[key] for key in ("layer_verdict", "risk_score", "risk_level", "risk_components", "decision", "decision_reason",
                                       "critic_result", "critic_reason", "retry_count", "trace")},
    }


# What each agent reads from the shared state, and which agent wrote each value. The UI shows these as the agent's input.
INPUT_KEYS = {
    "change_scan": ("repo", "old", "new"),
    "planner": ("old", "new", "scan"),
    "check_writing": ("old", "new", "scan", "focus"),
    "differential_run": ("old", "new", "api_checks", "browser_checks"),
    "layer_attribution": ("scan", "api_report", "browser_report", "start_error", "browser_error"),
    "risk_assessment": ("scan", "api_report", "browser_report", "start_error", "browser_error"),
    "decision": ("scan", "layer_verdict", "risk_score", "risk_level", "feedback"),
    "critic": ("decision", "scan", "api_report", "browser_report", "start_error", "browser_error"),
}
SOURCE = {"scan": "change_scan", "focus": "planner", "api_checks": "check_writing", "browser_checks": "check_writing", "api_report": "differential_run",
          "browser_report": "differential_run", "start_error": "differential_run", "browser_error": "differential_run",
          "layer_verdict": "layer_attribution", "risk_score": "risk_assessment", "risk_level": "risk_assessment", "decision": "decision"}
# The AI tasks (llm.ask task names) that belong to each agent.
NODE_TASKS = {"planner": ("planner",), "check_writing": ("api_checks", "browser_checks"), "decision": ("decision",), "critic": ("critic",)}


def _inputs(node: str, state: dict, produced: set[str]) -> dict:
    """Small values are copied. A value an earlier agent produced is a reference, so big results are not repeated in every step."""
    return {key: {"from": SOURCE[key]} if SOURCE.get(key) in produced else state.get(key, "") for key in INPUT_KEYS.get(node, ())}


def _ai_calls(node: str, after_id: int) -> list[dict]:
    return [{k: c[k] for k in ("task", "prompt", "answer", "fallback", "error")} for c in llm.call_log
            if c["id"] > after_id and c["task"] in NODE_TASKS.get(node, ())]


def stream_app_validation(repo: Path, old: str, new: str) -> Iterator[dict]:
    """Yields one event as each node finishes, then a final event carrying final_report.

    Each event has io: the agent's input, the AI calls it made (prompt and answer) and how long it took."""
    check_app_request(repo, old, new)
    state = dict(initial_app_state(Path(repo), old, new))
    produced: set[str] = set()  # replan and manual_review are produced too, harmless: nothing refers to them
    last_id = llm.call_log[-1]["id"] if llm.call_log else 0
    last_time = time.monotonic()
    for chunk in build_app_graph().stream(initial_app_state(Path(repo), old, new), stream_mode="updates",
                                          config={"recursion_limit": RECURSION_LIMIT}):
        for node, update in chunk.items():
            io = {"input": _inputs(node, state, produced), "ai": _ai_calls(node, last_id), "seconds": round(time.monotonic() - last_time, 1),
                  "messages_in": [m for m in state["messages"] if m["to"] == node]}  # what other agents had told this one before it ran
            last_id = llm.call_log[-1]["id"] if llm.call_log else last_id
            last_time = time.monotonic()
            produced.add(node)
            state.update({k: v for k, v in update.items() if k not in {"trace", "messages"}})
            state["trace"] = state["trace"] + update.get("trace", [])
            state["messages"] = state["messages"] + update.get("messages", [])
            yield {"node": node, "status": "done", "state_update": _for_ui(update), "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                   "io": io}
    yield {"node": "final", "status": "done", "state_update": {}, "timestamp": datetime.now().isoformat(timespec="milliseconds"),
           "final_report": _report(state)}


def run_app_validation(repo: Path, old: str, new: str) -> dict:
    for event in stream_app_validation(repo, old, new):
        if event["node"] == "final":
            return event["final_report"]
    raise RuntimeError("the workflow ended without a final event")
