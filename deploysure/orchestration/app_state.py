"""The shared state of the app-mode workflow (a whole app compared between two commits)."""
import operator
from typing import Annotated, TypedDict


class AppState(TypedDict, total=False):
    repo: str
    old: str  # a tag, branch or sha
    new: str
    old_sha: str
    new_sha: str
    scan: dict  # the change scan, with both maps. The entry point strips the maps before sending events to the UI.
    focus: list[str]  # what the Planner wants tested first, read by the Check writer
    focus_reason: str
    check_round: int  # how many times the Check writer has run: a second round repairs checks the Differential run found unreliable
    messages: Annotated[list[dict], operator.add]  # what agents tell each other: {"from", "to", "kind", "text"}
    api_checks: list[dict]
    browser_checks: list[dict]
    check_sources: dict[str, str]
    api_report: dict
    browser_report: dict
    start_error: str  # the new version did not start
    browser_error: str  # some checks could not run (no browser, or the old version did not start)
    layer_verdict: dict
    risk_score: int
    risk_level: str
    risk_components: dict[str, int]
    decision: str
    decision_reason: str
    critic_result: str
    critic_reason: str
    critic_rules: list[str]
    feedback: str
    retry_count: int
    trace: Annotated[list[str], operator.add]
