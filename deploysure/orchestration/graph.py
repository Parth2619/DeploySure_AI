"""Wires the agents into the LangGraph workflow. Nodes are plain functions: state in, partial state out."""
from langgraph.graph import END, START, StateGraph

from deploysure.agents.change_analyzer import change_analysis
from deploysure.agents.critic import critic
from deploysure.agents.decision_agent import decision
from deploysure.agents.impact_analyzer import impact_analysis
from deploysure.agents.planner import planner
from deploysure.agents.risk_assessor import risk_assessment
from deploysure.agents.test_executor import test_execution
from deploysure.agents.test_selector import test_selection
from deploysure.orchestration.routing import MAX_RETRIES, route_after_critic
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import DEFAULT_PROJECT

PIPELINE = [("planner", planner), ("change_analysis", change_analysis), ("impact_analysis", impact_analysis),
            ("test_selection", test_selection), ("test_execution", test_execution),
            ("risk_assessment", risk_assessment), ("decision", decision), ("critic", critic)]


def replan(state: ReleaseState) -> dict:
    count = state["retry_count"] + 1
    return {"retry_count": count, "trace": [f"replan: Critic rejected the decision, retry {count} of {MAX_RETRIES}"]}


def manual_review(state: ReleaseState) -> dict:
    # Fail closed: an unvalidated decision is never reported as DEPLOY.
    return {
        "decision": "HOLD",
        "decision_reason": f"Escalated to manual review: the Critic rejected the decision {MAX_RETRIES + 1} times.",
        "trace": ["manual_review: retry cap reached, escalated to a human, decision set to HOLD"],
    }


def build_graph():
    graph = StateGraph(ReleaseState)
    for name, fn in PIPELINE:
        graph.add_node(name, fn)
    graph.add_node("replan", replan)
    graph.add_node("manual_review", manual_review)

    graph.add_edge(START, "planner")
    for (a, _), (b, _) in zip(PIPELINE, PIPELINE[1:]):
        graph.add_edge(a, b)
    graph.add_conditional_edges("critic", route_after_critic,
                                {END: END, "replan": "replan", "manual_review": "manual_review"})
    graph.add_edge("replan", "planner")
    graph.add_edge("manual_review", END)
    return graph.compile()


def initial_state(release_id: str, project_id: str = DEFAULT_PROJECT) -> ReleaseState:
    return {"release_id": release_id, "project_id": project_id, "retry_count": 0, "feedback": "", "trace": []}
