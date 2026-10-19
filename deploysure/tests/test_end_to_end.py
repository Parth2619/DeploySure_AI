"""Both demo scenarios through the real graph, real pytest runs, mock LLM."""
import pytest

from deploysure.models import llm
from deploysure.orchestration.graph import build_graph, initial_state


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("DEPLOYSURE_LLM", "mock")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "1")


def run(release_id: str) -> tuple[dict, list[str]]:
    """Returns the final state and every decision made along the way, in order."""
    state, decisions = dict(initial_state(release_id)), []
    for chunk in build_graph().stream(initial_state(release_id), stream_mode="updates", config={"recursion_limit": 60}):
        for node, update in chunk.items():
            state.update({k: v for k, v in update.items() if k != "trace"})
            state["trace"] = state["trace"] + update.get("trace", [])
            if node == "decision":
                decisions.append(update["decision"])
    return state, decisions


def test_scenario_a_safe_release_deploys():
    state, decisions = run("v2.1")
    assert state["changed_files"] == ["notification.py"]
    assert len(state["selected_tests"]) == 6
    assert state["test_results"]["failed"] == 0
    assert state["risk_score"] == 12 and state["risk_level"] == "LOW"
    assert decisions == ["DEPLOY"]
    assert state["decision"] == "DEPLOY" and state["critic_result"] == "PASS" and state["retry_count"] == 0


def test_scenario_b_critic_rejects_seeded_deploy_then_blocks():
    state, decisions = run("v2.2")
    assert state["changed_files"] == ["payment.py"]
    assert len(state["selected_tests"]) == 20
    assert (state["test_results"]["passed"], state["test_results"]["failed"]) == (18, 2)
    assert "test_refund.py::test_refund" in state["test_results"]["failed_critical"]
    assert state["risk_score"] == 87 and state["risk_level"] == "CRITICAL"
    assert decisions == ["DEPLOY", "BLOCK"]
    assert state["decision"] == "BLOCK" and state["critic_result"] == "PASS" and state["retry_count"] == 1
    assert any("critic: FAIL" in line for line in state["trace"])


def test_stubborn_wrong_model_ends_in_manual_review(monkeypatch):
    # A model that always says DEPLOY must hit the retry cap, never loop forever, never ship.
    always_deploy = lambda prompt, task: {"decision": "DEPLOY", "reason": "looks fine"} if task == "decision" else {"reason": "r"}
    monkeypatch.setattr(llm, "_mock_answer", always_deploy)
    state, decisions = run("v2.2")
    assert decisions == ["DEPLOY", "DEPLOY", "DEPLOY"]
    assert state["retry_count"] == 2 and state["critic_result"] == "FAIL"
    assert state["decision"] == "HOLD" and "manual review" in state["decision_reason"].lower()
