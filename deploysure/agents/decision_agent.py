"""Decision: recommends DEPLOY, HOLD or BLOCK from the evidence. Uses the LLM."""
import os
from typing import Literal

from pydantic import BaseModel, field_validator

from deploysure.models.llm import ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.risk_formula import minimum_decision


class Verdict(BaseModel):
    decision: Literal["DEPLOY", "HOLD", "BLOCK"]
    reason: str

    @field_validator("decision", mode="before")
    @classmethod
    def _upper(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


def evidence_counts(state: ReleaseState) -> tuple[int, int, bool]:
    results = state["test_results"]
    failed_critical = len(results["failed_critical"])
    return failed_critical, results["failed"] - failed_critical, bool(results["error"])


def decision(state: ReleaseState) -> dict:
    # Disclosed demo switch: the first pass answers DEPLOY so the Critic has something to reject.
    if os.getenv("DEMO_SEED_WRONG_DECISION", "1") == "1" and state["retry_count"] == 0:
        return {
            "decision": "DEPLOY",
            "decision_reason": "[DEMO SEED] First pass is forced to DEPLOY for the demo. The Critic checks it next.",
            "trace": ["decision: DEPLOY (seeded by DEMO_SEED_WRONG_DECISION, first pass only)"],
        }
    failed_critical, failed_noncritical, test_error = evidence_counts(state)
    minimum, _ = minimum_decision(state["risk_level"], failed_critical, failed_noncritical, test_error)
    prompt = (
        "You decide whether a software release can go live. Answer DEPLOY, HOLD or BLOCK.\n"
        "Policy: a failed critical test or CRITICAL risk means BLOCK. HIGH risk or any failed test means HOLD at least. "
        "DEPLOY only if all selected tests pass and risk is LOW.\n"
        "EVIDENCE\n"
        f"changed_files: {state['changed_files']}\n"
        f"risk_score: {state['risk_score']}\n"
        f"risk_level: {state['risk_level']}\n"
        f"tests_selected: {len(state['selected_tests'])}\n"
        f"failed_critical: {failed_critical}\n"
        f"failed_noncritical: {failed_noncritical}\n"
        f"Critic feedback from the previous attempt: {state.get('feedback') or 'none'}\n"
        "Reply as JSON: {\"decision\": \"DEPLOY|HOLD|BLOCK\", \"reason\": \"one sentence\"}"
    )
    answer, fallback = ask(prompt, Verdict, task="decision",
                           default={"decision": minimum, "reason": "Model output invalid; applied the policy rules directly."})
    note = " (model output invalid, used policy rules)" if fallback else ""
    return {
        "decision": answer["decision"],
        "decision_reason": answer["reason"],
        "trace": [f"decision: {answer['decision']}{note}"],
    }
