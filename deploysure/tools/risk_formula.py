"""Deterministic release risk score, 0 to 100. No LLM involved.

Weights were chosen so the two demo scenarios land on 12 and 87. Change them
here and the deck numbers must be re-checked.
"""

CRITICAL_MODULES = {"payment", "checkout", "refund"}
# How much a customer notices this module when it breaks (0 to 10).
CUSTOMER_FACING = {"payment": 10, "checkout": 10, "refund": 10, "orders": 8, "notification": 8, "auth": 6}


def risk_level(score: int) -> str:
    if score <= 30:
        return "LOW"
    if score <= 60:
        return "MEDIUM"
    if score <= 80:
        return "HIGH"
    return "CRITICAL"


DECISION_RANK = {"DEPLOY": 0, "HOLD": 1, "BLOCK": 2}


def minimum_decision(level: str, failed_critical: int, failed_noncritical: int,
                     test_error: bool = False) -> tuple[str, list[str]]:
    """The policy floor: the least cautious decision allowed, plus the rules that fired."""
    fired = []
    if failed_critical:
        fired.append(f"{failed_critical} critical test(s) failed: BLOCK required")
    if level == "CRITICAL":
        fired.append("risk level CRITICAL: BLOCK required")
    if fired:
        return "BLOCK", fired
    if level == "HIGH":
        fired.append("risk level HIGH: HOLD at minimum")
    if level == "MEDIUM":
        fired.append("risk level MEDIUM: DEPLOY needs LOW risk, HOLD at minimum")
    if failed_noncritical:
        fired.append(f"{failed_noncritical} non-critical test(s) failed: HOLD at minimum")
    if test_error:
        fired.append("tests could not run: HOLD at minimum")
    if fired:
        return "HOLD", fired
    return "DEPLOY", ["all selected tests passed and risk is LOW: DEPLOY allowed"]


def decision_allowed(decision: str, minimum: str) -> bool:
    return DECISION_RANK[decision] >= DECISION_RANK[minimum]


def calculate_risk(changed_modules: list[str], dependents: int, lines_changed: int,
                   failed_critical: int, failed_noncritical: int) -> dict:
    """dependents = source modules (not tests) that import a changed module."""
    components = {
        "change_impact": min(25, 4 * dependents + lines_changed // 10),
        "critical_component": 30 if CRITICAL_MODULES & set(changed_modules) else 0,
        "failed_test_severity": min(30, 15 * failed_critical + 5 * failed_noncritical),
        "customer_facing": max((CUSTOMER_FACING.get(m, 0) for m in changed_modules), default=0),
        "failure_count": min(5, 3 * (failed_critical + failed_noncritical)),
    }
    score = max(0, min(100, sum(components.values())))
    return {"score": score, "level": risk_level(score), "components": components}


if __name__ == "__main__":
    print("A (notification, 1 dependent, 2 lines, no failures):", calculate_risk(["notification"], 1, 2, 0, 0))
    print("B (payment, 3 dependents, 4 lines, 2 critical failures):", calculate_risk(["payment"], 3, 4, 2, 0))
