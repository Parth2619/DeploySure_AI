"""Stage 4: a transparent, deterministic risk score from 0 to 100.

Rules (the same for every release):
  component_criticality  5      pricing handles money, so it always carries a little risk
  failure_rate           0-35   35 x (failed tests / all tests)
  critical_regression    30     at least one critical test failed
  assertion_severity     0-25   10 per failed critical test, 3 per other failed test, capped at 25
  missing_evidence       45     the tests could not give usable results
  unreviewed_change      5      the released file differs from the approved baseline
Levels: 0-30 LOW, 31-60 MEDIUM, 61-80 HIGH, 81-100 CRITICAL.
"""

LEVELS = ((30, "LOW"), (60, "MEDIUM"), (80, "HIGH"), (100, "CRITICAL"))


def risk_level(score: int) -> str:
    return next(name for limit, name in LEVELS if score <= limit)


def score_risk(release: dict, tests: dict) -> dict:
    parts = {"component_criticality": 5}
    if tests["problem"] and not tests["failed"]:
        parts["missing_evidence"] = 45
    elif tests["total"]:
        critical, other = len(tests["critical_failed"]), len(tests["failed"]) - len(tests["critical_failed"])
        parts["failure_rate"] = round(35 * len(tests["failed"]) / tests["total"])
        parts["critical_regression"] = 30 if critical else 0
        parts["assertion_severity"] = min(25, 10 * critical + 3 * other)
    parts["unreviewed_change"] = 5 if release["modified"] else 0
    score = min(100, sum(parts.values()))
    return {"score": score, "level": risk_level(score), "parts": parts}
