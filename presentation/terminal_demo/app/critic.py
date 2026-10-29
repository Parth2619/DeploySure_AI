"""Stage 6: an independent check of the decision.

The Critic does not call the gate. It starts from the raw test report and works out the least cautious decision the
evidence allows, then compares that with what the gate said. A weaker decision (for example DEPLOY with a critical
failure) is rejected. A stricter decision is allowed.
"""
STRICTNESS = {"DEPLOY": 0, "HOLD": 1, "BLOCK": 2}


def least_cautious_allowed(release: dict, tests: dict, risk: dict) -> str:
    if tests["critical_failed"] or risk["score"] >= 81:
        return "BLOCK"
    if release["missing"] or tests["problem"] or tests["failed"] or risk["score"] > 30:
        return "HOLD"
    return "DEPLOY"


def validate(decision: str, release: dict, tests: dict, risk: dict) -> dict:
    findings = []
    allowed = least_cautious_allowed(release, tests, risk)
    if STRICTNESS[decision] < STRICTNESS[allowed]:
        findings.append(f"Decision {decision} is less cautious than the evidence allows ({allowed} required).")
    if len(tests["passed"]) + len(tests["failed"]) + len(tests["errors"]) != tests["total"]:
        findings.append("The test counts do not add up, so the report cannot be trusted.")
    if tests["critical_failed"] and risk["level"] == "LOW":
        findings.append("The risk score is LOW although a critical test failed.")
    if decision == "DEPLOY" and (tests["failed"] or tests["problem"]):
        findings.append("DEPLOY was given although the test report shows failures or a problem.")
    if decision == "BLOCK" and not tests["critical_failed"] and risk["score"] < 81:
        findings.append("BLOCK is not backed by a critical failure or a critical risk score.")
    if findings:
        return {"verdict": "REJECTED", "required": allowed, "findings": findings,
                "explanation": "The decision contradicts the evidence: " + findings[0]}
    verdict = "APPROVED" if decision == "DEPLOY" else "CONFIRMED"
    return {"verdict": verdict, "required": allowed, "findings": [],
            "explanation": f"The test report, the risk score and the decision agree. The evidence requires at least {allowed}."}
