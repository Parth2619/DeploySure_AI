"""A stand-in for the AI used only by the test suite. It never ships and never touches the network.

It answers like a competent model: the decision follows the evidence lines in the prompt, the rest is canned text.
Answers are chosen by the name of the pydantic schema the agent asked for.
"""
import json
import re

from deploysure.models.llm import PLAN


def decision(prompt: str) -> dict:
    def field(name: str) -> str:
        m = re.search(rf"^{name}: (\w+)", prompt, re.MULTILINE)
        return m.group(1) if m else "0"

    if "breaking_findings:" in prompt:  # app mode: a whole app checked in old and new versions
        if int(field("breaking_findings")) > 0 or field("risk_level") == "CRITICAL":
            return {"decision": "BLOCK", "reason": "The change breaks the app, so it must not ship."}
        if int(field("behavior_changes")) > 0 or field("checks_incomplete") == "yes" or field("risk_level") in ("HIGH", "MEDIUM"):
            return {"decision": "HOLD", "reason": "Behavior changed or checks are incomplete, so a person should review it."}
        return {"decision": "DEPLOY", "reason": "No regression was found and risk is LOW."}
    if int(field("failed_critical")) > 0 or field("risk_level") == "CRITICAL":
        return {"decision": "BLOCK", "reason": "A critical test failed or risk is CRITICAL, so the release must not ship."}
    if field("risk_level") in ("HIGH", "MEDIUM") or int(field("failed_noncritical")) > 0 or field("tests_incomplete") == "yes":
        return {"decision": "HOLD", "reason": "Risk is elevated or testing is incomplete, so the release needs review first."}
    return {"decision": "DEPLOY", "reason": "All selected tests passed and risk is LOW."}


def answer(prompt: str, schema_name: str) -> dict:
    canned = {
        "Plan": {"tasks": PLAN},
        "AppPlan": {"focus": ["api_contract", "page_behavior"], "reason": "The change can break what the page and the API share."},
        "Explanation": {"explanation": "Modules that import the changed code can behave differently, so their tests are re-run."},
        "Justification": {"reason": "Tests were chosen from the impacted modules by the selection rule."},
        "Review": {"reason": "The decision was compared with the release policy rules."},
        "BrowserChecks": {"checks": [{"name": "Shopping flow", "reason": "the change may affect what the page shows", "steps": [
            {"action": "goto", "value": "/"}, {"action": "wait", "value": "500"}, {"action": "read", "selector": "#products li"},
            {"action": "click", "selector": "button.add"}, {"action": "click", "selector": "button.add"}, {"action": "wait", "value": "200"},
            {"action": "read", "selector": "#total"}, {"action": "click", "selector": "#place-order"}, {"action": "wait", "value": "500"},
            {"action": "read", "selector": "#result"}]}]},
        "ApiChecks": {"checks": [
            {"name": "Order with quantity 3", "method": "POST", "path": "/api/orders", "expect_status": 200,
             "json_body": {"items": [{"product_id": 3, "quantity": 3}]}, "reason": "the change touches how totals are computed"},
            {"name": "List products", "method": "GET", "path": "/api/products", "reason": "the page reads these fields"}]},
    }
    return decision(prompt) if schema_name == "Verdict" else canned[schema_name]


def groq_answer(prompt: str, schema) -> str:
    """Replaces llm._groq_answer in tests."""
    return json.dumps(answer(prompt, schema.__name__))
