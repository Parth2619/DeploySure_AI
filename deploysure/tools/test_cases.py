"""Test cases added from the UI. A test case is a title, a Critical flag and the pytest code the user wrote.

Each one becomes a generated test_case_<id>.py in every version, so it runs against all of them.
"""
import ast
import json
import re
from pathlib import Path

from deploysure.tools.code_reader import project_path, read_source, release_path
from deploysure.tools.project_store import (MAX_BYTES, ProjectError, list_versions, load_project, read_json,
                                            require_writable)


def _cases_dir(project_id: str) -> Path:
    return project_path(project_id) / "tests"


def list_test_cases(project_id: str) -> list[dict]:
    load_project(project_id)
    cases = [read_json(p, ("id", "title", "source", "critical")) for p in _cases_dir(project_id).glob("case_*.json")]
    return sorted(cases, key=lambda c: c["id"])


def _validated(title: str, source: str, critical: bool) -> dict:
    """The checked fields of a test case, without an id."""
    title = title.strip()
    if not 1 <= len(title) <= 80:
        raise ProjectError("title must be 1 to 80 characters")
    if len(source.encode("utf-8")) > MAX_BYTES:
        raise ProjectError(f"the test code is larger than {MAX_BYTES // 1024} KB")
    try:
        tree = ast.parse(source, filename="your test")
    except SyntaxError as err:
        raise ProjectError(f"your test has a syntax error on line {err.lineno}: {err.msg}")
    if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test") for n in ast.walk(tree)):
        raise ProjectError("the code needs at least one function whose name starts with test, for example def test_refund():")
    return {"title": title, "source": source, "critical": bool(critical)}


def _save(project_id: str, case: dict) -> dict:
    _cases_dir(project_id).mkdir(exist_ok=True)
    (_cases_dir(project_id) / f"case_{case['id']}.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
    return case


def add_test_case(project_id: str, title: str, source: str, critical: bool) -> dict:
    require_writable(project_id)
    fields = _validated(title, source, critical)
    next_id = max((c["id"] for c in list_test_cases(project_id)), default=0) + 1
    return _save(project_id, {"id": next_id, **fields})


def update_test_case(project_id: str, case_id: int, title: str, source: str, critical: bool) -> dict:
    require_writable(project_id)
    if not (_cases_dir(project_id) / f"case_{int(case_id)}.json").is_file():
        raise ProjectError(f"no test case {case_id}", 404)
    return _save(project_id, {"id": int(case_id), **_validated(title, source, critical)})


def list_all_tests(project_id: str) -> list[dict]:
    """Every test in the newest version, the project's own and the added cases, with the critical flag."""
    from deploysure.tools.project_store import analysis_lock
    from deploysure.tools.test_runner import CollectionError, collect_tests

    versions = list_versions(project_id)
    if not versions:
        return []
    newest = versions[-1]["version"]
    folder = release_path(newest, project_id)
    if not analysis_lock(project_id, newest).locked():  # a running analysis has already written the files
        materialize_tests(project_id, folder)
    try:
        return collect_tests(folder, critical_modules=set(load_project(project_id)["critical_modules"]))
    except CollectionError as err:
        raise ProjectError(str(err))


def delete_test_case(project_id: str, case_id: int) -> None:
    require_writable(project_id)
    path = _cases_dir(project_id) / f"case_{int(case_id)}.json"
    if not path.is_file():
        raise ProjectError(f"no test case {case_id}", 404)
    path.unlink()


TEST_FILE_RE = re.compile(r"test_[A-Za-z0-9_]+\.py")


def _newest_test_file(project_id: str, file: str) -> tuple[str, Path]:
    """The project's own test file in its newest version. Generated and config files are not allowed."""
    if not TEST_FILE_RE.fullmatch(file) or file.startswith("test_case_"):
        raise ProjectError("only the project's own test files (test_*.py) can be opened")
    versions = list_versions(project_id)
    if not versions:
        raise ProjectError("this project has no versions", 404)
    newest = versions[-1]["version"]
    path = release_path(newest, project_id) / file
    if not path.is_file():
        raise ProjectError(f"{file} is not in version {newest}", 404)
    return newest, path


def read_test_file(project_id: str, file: str) -> dict:
    project = load_project(project_id)
    newest, path = _newest_test_file(project_id, file)
    editable = not project.get("protected") and file not in project.get("locked_test_files", [])
    return {"file": file, "version": newest, "source": read_source(path), "editable": editable}


def save_test_file(project_id: str, file: str, source: str) -> dict:
    """Replaces a test file in the newest version only. Older versions keep their own copy."""
    project = require_writable(project_id)
    if file in project.get("locked_test_files", []):
        raise ProjectError(f"{file} is locked in {project['name']} so the demo scenario stays the same.", 403)
    _, path = _newest_test_file(project_id, file)
    if len(source.encode("utf-8")) > MAX_BYTES:
        raise ProjectError(f"{file} is larger than {MAX_BYTES // 1024} KB")
    try:
        compile(source, file, "exec")
    except SyntaxError as err:
        raise ProjectError(f"{file} has a syntax error on line {err.lineno}: {err.msg}")
    path.write_text(source, encoding="utf-8", newline="\n")
    return read_test_file(project_id, file)


def render_test(case: dict) -> str:
    """The user's code as written. The title never goes into code, so it cannot inject anything."""
    text = case["source"].rstrip() + "\n"
    if case["critical"]:
        # Added at the end so a "from __future__" line in the user's code can stay first.
        text += "\n\nimport pytest as _pytest\n\npytestmark = _pytest.mark.critical\n"
    return text


def materialize_tests(project_id: str, version_dir: Path) -> int:
    """Rewrites test_case_<id>.py in a version folder from the saved cases. Returns how many."""
    for old in version_dir.glob("test_case_*.py"):
        old.unlink()
    cases = list_test_cases(project_id)
    for case in cases:
        (version_dir / f"test_case_{case['id']}.py").write_text(render_test(case), encoding="utf-8")
    return len(cases)
