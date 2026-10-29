"""The one shared state every node reads and writes."""
import operator
from typing import Annotated, TypedDict


class ReleaseState(TypedDict, total=False):
    release_id: str
    project_id: str
    baseline: str
    tasks: list[str]
    # change analysis
    changed_files: list[str]
    changed_functions: dict[str, list[str]]
    lines_changed: int
    # impact analysis and test selection
    impacted_modules: list[str]
    impact_explanation: str
    selected_tests: list[str]
    selection_reason: str
    all_test_ids: list[str]  # every test in the version, selected or not, so the UI can list them
    critical_tests: list[str]  # ids of selected tests that count as critical
    uncovered_modules: list[str]  # changed modules that no test imports
    selection_error: str  # set when pytest could not collect the tests
    # execution and risk
    test_results: dict
    risk_score: int
    risk_level: str
    risk_components: dict[str, int]
    # decision and critic
    decision: str
    decision_reason: str
    critic_result: str  # PASS or FAIL
    critic_reason: str
    critic_rules: list[str]
    feedback: str  # critic's complaint, read by planner and decision on the next pass
    retry_count: int
    # Each node returns only its own new line; operator.add appends it.
    trace: Annotated[list[str], operator.add]
