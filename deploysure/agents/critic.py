"""Critic: checks the decision against the policy in code first, then the LLM writes the reasoning.

The rule check alone decides PASS or FAIL, so a weak model cannot talk its way past the policy.
"""
from pydantic import BaseModel

from deploysure.agents.decision_agent import evidence_counts
from deploysure.models.llm import ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.risk_formula import decision_allowed, minimum_decision


class Review(BaseModel):
    reason: str


def critic(state: ReleaseState) -> dict:
    failed_critical, failed_noncritical, test_error = evidence_counts(state)
    minimum, rules = minimum_decision(state["risk_level"], failed_critical, failed_noncritical, test_error)
    passed = decision_allowed(state["decision"], minimum)
    verdict = "PASS" if passed else "FAIL"
    rule_text = "; ".join(rules)
    summary = (f"Decision {state['decision']} is consistent with the rules ({rule_text})." if passed else
               f"Decision {state['decision']} breaks the rules, at least {minimum} is required ({rule_text}).")
    prompt = (
        "A rule engine already reviewed a release decision. The result is final, do not question it. "
        + ("Write one sentence saying why the decision satisfies the rules. " if passed else
           "Write one sentence saying why the decision breaks the rules. ")
        + "Reply as JSON: {\"reason\": \"...\"}.\n"
        f"decision: {state['decision']}\nrequired_at_least: {minimum}\nrules_fired: {rules}\nresult: {verdict}"
    )
    answer, fallback = ask(prompt, Review, task="critic", default={"reason": "Written reasoning unavailable."})
    note = " (model output invalid, rule summary only)" if fallback else ""
    return {
        "critic_result": verdict,
        "critic_reason": f"{summary} {answer['reason']}",
        "critic_rules": rules,
        "feedback": "" if passed else f"Your decision {state['decision']} was rejected: {rule_text}. Required: {minimum} or stricter.",
        "trace": [f"critic: {verdict}, decision {state['decision']} vs required at least {minimum}{note}"],
    }
