"""Impact analysis: import graph finds affected modules, the LLM only explains it."""
from pathlib import Path

from pydantic import BaseModel

from deploysure.models.llm import ask
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.dependency_analyzer import build_import_graph, impacted_modules


class Explanation(BaseModel):
    explanation: str


def impact_analysis(state: ReleaseState) -> dict:
    changed = [Path(f).stem for f in state["changed_files"]]
    impacted = impacted_modules(build_import_graph(release_path(state["release_id"])), changed)
    default = {"explanation": f"Changed {', '.join(changed)}; modules that import it are also affected: {', '.join(impacted)}."}
    prompt = (
        "Explain in one sentence why these modules are affected by the change. "
        "Reply as JSON: {\"explanation\": \"...\"}.\n"
        f"changed_modules: {changed}\nimpacted_modules: {impacted}"
    )
    answer, fallback = ask(prompt, Explanation, task="impact", default=default)
    note = " (model output invalid, used default text)" if fallback else ""
    return {
        "impacted_modules": impacted,
        "impact_explanation": answer["explanation"],
        "trace": [f"impact_analysis: {len(impacted)} module(s) impacted: {', '.join(impacted)}{note}"],
    }
