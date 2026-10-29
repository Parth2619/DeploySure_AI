"""App-mode nodes that judge the evidence: which layer is at fault, the risk, the Decision and the Critic.

Same split as the original workflow: the layer verdict, the risk score and the Critic's rule floor are plain code.
The model recommends a decision and writes explanations, and it can never go below the floor.
"""
from deploysure.agents.app_nodes import say
from deploysure.agents.critic import Review
from deploysure.agents.decision_agent import Verdict
from deploysure.models import llm
from deploysure.models.llm import ask
from deploysure.orchestration.app_state import AppState
from deploysure.tools import app_policy
from deploysure.tools.layer_verdict import layer_verdict
from deploysure.tools.risk_formula import decision_allowed


def _evidence(state: AppState) -> tuple:
    """The inputs every judging function needs, in the order the policy functions take them."""
    return (state["scan"], state["api_report"]["results"], state["browser_report"]["results"],
            state.get("start_error", ""), state.get("browser_error", ""))


def layer_attribution(state: AppState) -> dict:
    verdict = layer_verdict(*_evidence(state))
    told = f"The fault is in: {verdict['primary']} ({verdict['confidence']} confidence). " + (verdict["reasons"][0] if verdict["reasons"] else "")
    return {"layer_verdict": verdict, "messages": [say("layer_attribution", "decision", "info", told.strip())],
            "trace": [f"layer_attribution: {verdict['primary']} ({verdict['confidence']} confidence)"]}


def app_risk_assessment(state: AppState) -> dict:
    risk = app_policy.app_risk(*_evidence(state))
    biggest = sorted(((k, v) for k, v in risk["components"].items() if v), key=lambda kv: -kv[1])[:2]
    told = f"Risk {risk['score']} ({risk['level']}). " + ("Biggest parts: " + ", ".join(f"{k} {v}" for k, v in biggest) + "." if biggest else "Nothing adds risk.")
    return {"risk_score": risk["score"], "risk_level": risk["level"], "risk_components": risk["components"],
            "messages": [say("risk_assessment", "decision", "info", told)],
            "trace": [f"risk_assessment: score {risk['score']} ({risk['level']}), components {risk['components']}"]}


def app_decision(state: AppState) -> dict:
    counts = app_policy.evidence_counts(*_evidence(state))
    minimum, _ = app_policy.minimum_app_decision(*_evidence(state))
    verdict = state["layer_verdict"]
    notes = [m for m in state.get("messages", []) if m["to"] == "decision"][-6:]  # what the other agents told this one
    prompt = (
        "You decide whether a change to a web app can go live. Answer DEPLOY, HOLD or BLOCK.\n"
        "Policy: a broken page, a page and API that no longer agree, or an app that does not start mean BLOCK. "
        "A changed value or checks that could not run mean HOLD at least. DEPLOY only if nothing regressed and risk is LOW.\n"
        "EVIDENCE\n"
        f"changed_layers: {', '.join(state['scan']['layers']) or 'none'}\n"
        f"risk_score: {state['risk_score']}\n"
        f"risk_level: {state['risk_level']}\n"
        f"breaking_findings: {counts['breaking']}\n"
        f"behavior_changes: {counts['behavior_changes']}\n"
        f"checks_incomplete: {'yes' if counts['incomplete'] else 'no'}\n"
        f"faulty_layer: {verdict['primary']} ({verdict['confidence']} confidence)\n"
        + "".join(f"- {r}\n" for r in verdict["reasons"][:3])
        + f"Critic feedback from the previous attempt: {state.get('feedback') or 'none'}\n"
        + "Notes from the other agents:\n" + "".join(f"- {m['from']}: {m['text']}\n" for m in notes)
        + 'Reply as JSON: {"decision": "DEPLOY|HOLD|BLOCK", "reason": "one sentence"}'
    )
    answer, fallback = ask(prompt, Verdict, task="decision",
                           default={"decision": minimum, "reason": "The model was not available; applied the policy rules directly."})
    note = llm.fallback_note("used the policy rules") if fallback else ""
    return {"decision": answer["decision"], "decision_reason": answer["reason"],
            "messages": [say("decision", "critic", "info", f"I recommend {answer['decision']}: {answer['reason']}")],
            "trace": [f"decision: {answer['decision']}{note}"]}


def app_critic(state: AppState) -> dict:
    minimum, rules = app_policy.minimum_app_decision(*_evidence(state))
    passed = decision_allowed(state["decision"], minimum)
    verdict = "PASS" if passed else "FAIL"
    rule_text = "; ".join(rules)
    summary = (f"Decision {state['decision']} is consistent with the rules ({rule_text})." if passed else
               f"Decision {state['decision']} breaks the rules, at least {minimum} is required ({rule_text}).")
    prompt = (
        "A rule engine already reviewed a release decision. The result is final, do not question it. "
        + ("Write one sentence saying why the decision satisfies the rules. " if passed else
           "Write one sentence saying why the decision breaks the rules. ")
        + 'Reply as JSON: {"reason": "..."}.\n'
        f"decision: {state['decision']}\nrequired_at_least: {minimum}\nrules_fired: {rules}\nresult: {verdict}"
    )
    answer, fallback = ask(prompt, Review, task="critic", default={"reason": "Written reasoning unavailable."})
    note = llm.fallback_note("rule summary only") if fallback else ""
    feedback = "" if passed else f"Your decision {state['decision']} was rejected: {rule_text}. Required: {minimum} or stricter."
    return {"critic_result": verdict, "critic_reason": f"{summary} {answer['reason']}", "critic_rules": rules, "feedback": feedback,
            "messages": [] if passed else [say("critic", "decision", "challenge", feedback)],
            "trace": [f"critic: {verdict}, decision {state['decision']} vs required at least {minimum}{note}"]}
