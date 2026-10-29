"""The app-mode workflow: a whole app, compared between two commits.

    change_scan -> planner -> check_writing -> differential_run -> layer_attribution -> risk_assessment -> decision -> critic
    differential_run -> check_writing   once, if it found AI-written checks unreliable (the old version failed them)
    critic PASS -> END
    critic FAIL -> replan -> decision     (retry_count < MAX_RETRIES)
    critic FAIL -> manual_review -> END   (retry_count >= MAX_RETRIES)

The agents work on one shared state and send each other messages: the scan tells the Planner what changed, the Planner tells the
Check writer what to test first, the Differential run can send unreliable checks back, and the Critic challenges the Decision.
A decision retry goes back to the decision only: the evidence from two live apps is gathered once.
"""
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from deploysure.agents.app_judge import app_critic, app_decision, app_risk_assessment, layer_attribution
from deploysure.agents.app_nodes import app_planner, change_scan, check_writing, differential_run, repair_requested
from deploysure.orchestration.app_state import AppState
from deploysure.orchestration.graph import manual_review, replan
from deploysure.orchestration.routing import route_after_critic

PIPELINE = [("change_scan", change_scan), ("planner", app_planner), ("check_writing", check_writing),
            ("differential_run", differential_run), ("layer_attribution", layer_attribution),
            ("risk_assessment", app_risk_assessment), ("decision", app_decision), ("critic", app_critic)]


def route_after_run(state: AppState) -> str:
    """Loops back to the Check writer when the Differential run asked for a repair. repair_requested allows it only once."""
    return "check_writing" if repair_requested(state) else "layer_attribution"


def build_app_graph():
    graph = StateGraph(AppState)
    for name, fn in PIPELINE:
        graph.add_node(name, fn)
    graph.add_node("replan", replan)
    graph.add_node("manual_review", manual_review)
    graph.add_edge(START, "change_scan")
    for (a, _), (b, _) in zip(PIPELINE, PIPELINE[1:]):
        if a != "differential_run":
            graph.add_edge(a, b)
    graph.add_conditional_edges("differential_run", route_after_run, {"check_writing": "check_writing", "layer_attribution": "layer_attribution"})
    graph.add_conditional_edges("critic", route_after_critic, {END: END, "replan": "replan", "manual_review": "manual_review"})
    graph.add_edge("replan", "decision")
    graph.add_edge("manual_review", END)
    return graph.compile()


def initial_app_state(repo: Path, old: str, new: str) -> AppState:
    return {"repo": str(repo), "old": old, "new": new, "retry_count": 0, "feedback": "", "check_round": 0, "messages": [], "trace": []}
