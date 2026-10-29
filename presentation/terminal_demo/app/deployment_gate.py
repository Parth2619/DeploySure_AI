"""Stage 5: explicit rules turn the evidence into DEPLOY, HOLD or BLOCK. The first rule that applies wins.

  1. a critical test failed                    BLOCK  (never outvoted by a low score)
  2. risk score 81 or more                     BLOCK
  3. the release or the test evidence is missing, or the tests could not run   HOLD
  4. any other test failed                     HOLD
  5. risk score above 30                       HOLD
  6. otherwise                                 DEPLOY
"""

BLOCK_AT_RISK = 81
DEPLOY_MAX_RISK = 30


def decide(release: dict, tests: dict, risk: dict) -> dict:
    if tests["critical_failed"]:
        return _result("BLOCK", "A required regression test failed: " + ", ".join(tests["critical_failed"]) + ".")
    if risk["score"] >= BLOCK_AT_RISK:
        return _result("BLOCK", f"Risk score {risk['score']} is at or above the blocking limit of {BLOCK_AT_RISK}.")
    if release["missing"]:
        return _result("HOLD", "Release file missing: " + ", ".join(release["missing"]) + ".")
    if tests["problem"]:
        return _result("HOLD", "No usable test evidence: " + tests["problem"] + ".")
    if tests["failed"]:
        return _result("HOLD", f"{len(tests['failed'])} non-critical test(s) failed, so a person must review the release.")
    if risk["score"] > DEPLOY_MAX_RISK:
        return _result("HOLD", f"Risk score {risk['score']} is above the deploy limit of {DEPLOY_MAX_RISK}.")
    return _result("DEPLOY", "No release-blocking regressions detected. All required tests passed.")


def _result(decision: str, reason: str) -> dict:
    return {"decision": decision, "reason": reason}
