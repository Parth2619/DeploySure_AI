"""Test execution: runs real pytest. Results are never produced by an LLM."""
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.project_store import load_project
from deploysure.tools.test_runner import run_tests


def test_execution(state: ReleaseState) -> dict:
    error = state.get("selection_error") or ("" if state["selected_tests"] else "no tests cover this change")
    if error:
        # Running pytest with no ids would run everything, so report the gap instead. It counts as a test error (HOLD).
        results = {"total": 0, "passed": 0, "failed": 0, "results": [], "failed_tests": [], "failed_critical": [],
                   "error": error}
    else:
        critical = set(load_project(state["project_id"])["critical_modules"])
        results = run_tests(release_path(state["release_id"], state["project_id"]), state["selected_tests"],
                            critical_modules=critical, critical_ids=set(state.get("critical_tests", [])))
    results["uncovered"] = list(state.get("uncovered_modules", []))
    if results["error"]:
        line = f"test_execution: tests could not run: {results['error']}"
    else:
        line = (f"test_execution: {results['passed']} passed, {results['failed']} failed "
                f"({len(results['failed_critical'])} critical) of {results['total']}")
    if results["uncovered"]:
        line += f"; no test covers: {', '.join(results['uncovered'])}"
    return {"test_results": results, "trace": [line]}
