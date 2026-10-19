"""Risk assessment: the fixed formula in tools/risk_formula.py. No LLM."""
from pathlib import Path

from deploysure.orchestration.state import ReleaseState
from deploysure.tools.dependency_analyzer import is_test_module
from deploysure.tools.risk_formula import calculate_risk


def risk_assessment(state: ReleaseState) -> dict:
    changed = [Path(f).stem for f in state["changed_files"]]
    dependents = [m for m in state["impacted_modules"] if m not in changed and not is_test_module(m)]
    results = state["test_results"]
    failed_critical = len(results["failed_critical"])
    risk = calculate_risk(changed, len(dependents), state["lines_changed"],
                          failed_critical, results["failed"] - failed_critical)
    return {
        "risk_score": risk["score"],
        "risk_level": risk["level"],
        "risk_components": risk["components"],
        "trace": [f"risk_assessment: score {risk['score']} ({risk['level']}), components {risk['components']}"],
    }
