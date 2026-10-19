"""Test execution: runs real pytest. Results are never produced by an LLM."""
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.test_runner import run_tests


def test_execution(state: ReleaseState) -> dict:
    results = run_tests(release_path(state["release_id"]), state["selected_tests"])
    if results["error"]:
        line = f"test_execution: tests could not run: {results['error']}"
    else:
        line = (f"test_execution: {results['passed']} passed, {results['failed']} failed "
                f"({len(results['failed_critical'])} critical) of {results['total']}")
    return {"test_results": results, "trace": [line]}
