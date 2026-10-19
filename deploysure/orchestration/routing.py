"""Decides what happens after the Critic. This is what stops the retry loop."""
from langgraph.graph import END

from deploysure.orchestration.state import ReleaseState

MAX_RETRIES = 2


def route_after_critic(state: ReleaseState) -> str:
    if state["critic_result"] == "PASS":
        return END
    if state["retry_count"] < MAX_RETRIES:
        return "replan"
    return "manual_review"
