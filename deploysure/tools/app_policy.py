"""Risk score and decision floor for a whole app. Deterministic, no LLM, like tools/risk_formula.py.

The score (0 to 100) adds up what the evidence shows. The floor is the least cautious decision allowed, and the Critic
enforces it in code: a language model can recommend more caution than the floor, never less.
"""
from deploysure.tools.risk_formula import risk_level

CODE_LAYERS = {"backend", "frontend", "dependencies", "config"}
BREAKING_API_KINDS = {"status_changed", "field_removed", "app_error"}


def _regressions(results: list[dict]) -> list[dict]:
    return [r for r in results if r["verdict"] == "regression"]


def _breaking_api(results: list[dict]) -> list[dict]:
    return [r for r in _regressions(results) if any(d["kind"] in BREAKING_API_KINDS for d in r["differences"])]


def app_risk(scan: dict, api: list[dict], browser: list[dict], start_error: str = "", browser_error: str = "") -> dict:
    files = sum(len(paths) for layer, paths in scan["layers"].items() if layer in CODE_LAYERS)
    breaking = len(_breaking_api(api))
    components = {
        "change_impact": min(15, 3 * files + 2 * len(scan["endpoint_changes"])),
        "contract_break": min(40, 30 * len(scan["contract_issues"])),
        "api_regression": min(40, 40 * breaking + 35 * (len(_regressions(api)) - breaking)),  # a changed value is a smaller worry than a broken answer
        "ui_regression": min(40, 40 * len(_regressions(browser))),
        "not_verified": 10 if browser_error else 0,
    }
    if start_error:
        components["start_failure"] = 100
    score = min(100, sum(components.values()))
    return {"score": score, "level": risk_level(score), "components": components}


def evidence_counts(scan: dict, api: list[dict], browser: list[dict], start_error: str = "", browser_error: str = "") -> dict:
    """The numbers the Decision agent is shown."""
    breaking = len(scan["contract_issues"]) + len(_regressions(browser)) + len(_breaking_api(api)) + (1 if start_error else 0)
    return {"breaking": breaking, "behavior_changes": len(_regressions(api)) - len(_breaking_api(api)),
            "unreliable": sum(r["verdict"] == "unreliable" for r in api + browser),
            "incomplete": bool(start_error or browser_error or not (api or browser))}


def minimum_app_decision(scan: dict, api: list[dict], browser: list[dict], start_error: str = "", browser_error: str = "") -> tuple[str, list[str]]:
    """The least cautious decision allowed, with the rules that fired."""
    block, hold = [], []
    if start_error:
        block.append("the new version does not start")
    if scan["contract_issues"]:
        block.append(f"the page and the API no longer agree ({len(scan['contract_issues'])} issue(s))")
    if _regressions(browser):
        block.append("the page behaves differently in a way that looks broken")
    if _breaking_api(api):
        block.append("an API answer lost a field, changed its status or failed")
    risk = app_risk(scan, api, browser, start_error, browser_error)
    if risk["level"] == "CRITICAL":
        block.append("risk level CRITICAL")
    if block:
        return "BLOCK", block
    if _regressions(api):
        hold.append("an API answer changed value, so a person must confirm the change is intended")
    if browser_error:
        hold.append("some checks could not run, so the app is unverified")
    checks = api + browser
    if not checks:
        hold.append("no check ran, so nothing was verified")
    elif all(r["verdict"] == "unreliable" for r in checks):
        hold.append("no check could be trusted, because the old version already failed them")
    if risk["level"] in {"MEDIUM", "HIGH"}:
        hold.append(f"risk level {risk['level']}: HOLD at minimum")
    if hold:
        return "HOLD", hold
    return "DEPLOY", ["no regression found, every check ran and risk is LOW: DEPLOY allowed"]
