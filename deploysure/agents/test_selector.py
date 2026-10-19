"""Test selection: a fixed rule picks the tests, the LLM only writes the justification."""
from pathlib import Path

from pydantic import BaseModel

from deploysure.models.llm import ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.risk_formula import CRITICAL_MODULES
from deploysure.tools.test_runner import collect_tests


class Justification(BaseModel):
    reason: str


def test_selection(state: ReleaseState) -> dict:
    all_tests = collect_tests(release_path(state["release_id"]))
    changed = {Path(f).stem for f in state["changed_files"]}
    if changed & CRITICAL_MODULES:
        # Money paths are never sampled: a critical change runs the whole suite.
        selected = [t["id"] for t in all_tests]
        rule = f"critical module changed ({', '.join(sorted(changed & CRITICAL_MODULES))}): run the full suite"
    else:
        impacted = set(state["impacted_modules"])
        selected = [t["id"] for t in all_tests if t["id"].split("::")[0].removesuffix(".py") in impacted]
        rule = "run tests of the changed and impacted modules"
    prompt = (
        "Justify this test selection in one sentence. Reply as JSON: {\"reason\": \"...\"}.\n"
        f"rule: {rule}\ntests_selected: {len(selected)} of {len(all_tests)}"
    )
    answer, fallback = ask(prompt, Justification, task="test_selection", default={"reason": rule})
    note = " (model output invalid, used rule text)" if fallback else ""
    return {
        "selected_tests": selected,
        "selection_reason": f"{rule}. {answer['reason']}",
        "trace": [f"test_selection: {len(selected)} of {len(all_tests)} tests selected, rule: {rule}{note}"],
    }
