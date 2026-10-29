"""Change analysis: which files and functions differ from the baseline. No LLM."""
from deploysure.orchestration.state import ReleaseState
from deploysure.tools.code_reader import release_path
from deploysure.tools.diff_tool import diff_releases


def change_analysis(state: ReleaseState) -> dict:
    project = state["project_id"]
    diff = diff_releases(release_path(state["baseline"], project), release_path(state["release_id"], project))
    functions = {f: d["functions"] for f, d in diff["details"].items()}
    summary = "; ".join(f"{f} ({', '.join(fn)})" for f, fn in functions.items()) or "no changes"
    return {
        "changed_files": diff["changed_files"],
        "changed_functions": functions,
        "lines_changed": diff["lines_changed"],
        "trace": [f"change_analysis: {diff['lines_changed']} line(s) changed vs {state['baseline']}: {summary}"],
    }
