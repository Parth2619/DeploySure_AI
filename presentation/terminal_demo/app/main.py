"""The whole pipeline: analyze, select tests, run them, score risk, decide, let the Critic check the decision.

Exit codes: 0 DEPLOY, 1 BLOCK, 2 HOLD, 3 the Critic rejected the decision.
"""
from pathlib import Path

from app import critic, deployment_gate, release_analyzer, risk_scorer, test_runner, test_selector

EXIT_CODES = {"DEPLOY": 0, "BLOCK": 1, "HOLD": 2}
REJECTED_EXIT_CODE = 3
WIDTH = 52


def _stage(out, number: int, label: str, status: str) -> None:
    out(f"[{number}/6] {label} ".ljust(40, ".") + f" {status}")


def run_pipeline(root: Path, out=print) -> dict:
    """Runs every stage and prints progress through out(). A failing test is evidence here, never a crash."""
    root = Path(root)
    out("=" * WIDTH + "\n" + "AI-POWERED DEPLOYMENT RISK ANALYZER".center(WIDTH) + "\n" + "=" * WIDTH + "\n")

    release = release_analyzer.analyze_release(root)
    _stage(out, 1, "Analyzing release", "COMPLETE")
    selected = test_selector.select_tests(release["components"], root)
    _stage(out, 2, "Selecting relevant tests", "COMPLETE")
    tests = test_runner.run_tests(root, selected)
    state = ("EXECUTION PROBLEM" if tests["problem"] and not tests["failed"] else
             "REGRESSION FOUND" if tests["failed"] else "ALL PASSED")
    _stage(out, 3, "Executing tests", state)
    risk = risk_scorer.score_risk(release, tests)
    _stage(out, 4, "Calculating release risk", risk["level"])
    gate = deployment_gate.decide(release, tests, risk)
    _stage(out, 5, "Deployment gate", gate["decision"])
    check = critic.validate(gate["decision"], release, tests, risk)
    _stage(out, 6, "Critic validation", check["verdict"])

    # A rejected decision is never passed on: the Critic's minimum replaces it.
    valid = check["verdict"] != "REJECTED"
    final = gate["decision"] if valid else check["required"]
    reason = gate["reason"] if valid else f"Critic rejected the gate's decision ({gate['decision']}). {check['explanation']}"
    exit_code = EXIT_CODES[final] if valid else REJECTED_EXIT_CODE

    out(f"\nRelease:  {release['release_id']}  ({release['summary']})")
    for t in selected:
        out(f"Tests:    {t['file']} ({t['reason']})")
    out(f"Results:  {len(tests['passed'])} passed, {len(tests['failed'])} failed, {len(tests['errors'])} errors")
    for name in tests["failed"] + tests["errors"]:
        tag = "CRITICAL" if name in tests["critical_failed"] else "normal"
        out(f"          FAILED [{tag}] {name}: {tests['messages'].get(name, '')}")
    if tests["problem"]:
        out(f"          Problem: {tests['problem']}")
    out(f"\nRisk Score: {risk['score']}/100 ({risk['level']})")
    for name, points in risk["parts"].items():
        if points:
            out(f"  +{points:<3} {name.replace('_', ' ')}")
    out(f"\nFinal Decision: {final}")
    out(f"Reason: {reason}")
    out(f"Critic: {check['verdict']}. {check['explanation']}")
    return {"release": release, "selected": selected, "tests": tests, "risk": risk, "gate": gate, "critic": check,
            "final": final, "reason": reason, "valid": valid, "exit_code": exit_code}
