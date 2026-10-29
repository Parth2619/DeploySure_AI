"""Test selection: a fixed rule picks the tests, the LLM only writes the justification."""
from pathlib import Path

from pydantic import BaseModel

from deploysure.models import llm
from deploysure.models.llm import ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.dependency_analyzer import build_import_graph, impacted_modules, is_test_module
from deploysure.tools.project_store import load_project
from deploysure.tools.test_runner import CollectionError, collect_tests


class Justification(BaseModel):
    reason: str


def test_selection(state: ReleaseState) -> dict:
    release_dir = release_path(state["release_id"], state["project_id"])
    critical_modules = set(load_project(state["project_id"])["critical_modules"])
    try:
        all_tests = collect_tests(release_dir, critical_modules=critical_modules)
    except CollectionError as err:
        # Broken tests are not a pass. The executor turns this into a test error, which means HOLD.
        return {"selected_tests": [], "all_test_ids": [], "critical_tests": [], "uncovered_modules": [], "selection_error": str(err),
                "selection_reason": "The tests could not be collected.", "trace": [f"test_selection: {err}"]}
    changed = {Path(f).stem for f in state["changed_files"]}
    if not changed:
        # Nothing in the code changed (for example only a test case was added): run everything.
        selected = [t["id"] for t in all_tests]
        rule = "no code changed: run the full suite"
    elif changed & critical_modules:
        # Money paths are never sampled: a critical change runs the whole suite.
        selected = [t["id"] for t in all_tests]
        rule = f"critical module changed ({', '.join(sorted(changed & critical_modules))}): run the full suite"
    else:
        impacted = set(state["impacted_modules"])
        selected = [t["id"] for t in all_tests if t["id"].split("::")[0].removesuffix(".py") in impacted]
        rule = "run tests of the changed and impacted modules"
    # A changed module that no test imports is never "safe because the other tests passed".
    graph = build_import_graph(release_dir)
    uncovered = sorted(m for m in changed if not any(is_test_module(x) for x in impacted_modules(graph, [m])))
    prompt = (
        "Justify this test selection in one sentence. Reply as JSON: {\"reason\": \"...\"}.\n"
        f"rule: {rule}\ntests_selected: {len(selected)} of {len(all_tests)}"
    )
    answer, fallback = ask(prompt, Justification, task="test_selection", default={"reason": rule})
    note = llm.fallback_note("used rule text") if fallback else ""
    gap = f"; no test covers: {', '.join(uncovered)}" if uncovered else ""
    return {
        "selected_tests": selected,
        "all_test_ids": [t["id"] for t in all_tests],
        "critical_tests": [t["id"] for t in all_tests if t["critical"] and t["id"] in selected],
        "uncovered_modules": uncovered,
        "selection_error": "",
        "selection_reason": f"{rule}. {answer['reason']}",
        "trace": [f"test_selection: {len(selected)} of {len(all_tests)} tests selected, rule: {rule}{gap}{note}"],
    }
