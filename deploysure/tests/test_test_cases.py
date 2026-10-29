import json

import pytest

from deploysure.tools import code_reader, project_store as ps, test_cases as tc
from deploysure.tools.project_store import ProjectError
from deploysure.tools.test_runner import run_tests

PASSING = "import shop\n\n\ndef test_adds():\n    assert shop.add(2, 3) == 5\n"
FAILING = "import shop\n\n\ndef test_adds():\n    assert shop.add(2, 3) == 6\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A temporary project 'shop' whose module shop.py has add(a, b)."""
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    src = tmp_path / "src"
    src.mkdir()
    (src / "shop.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "test_shop.py").write_text("import shop\n\ndef test_add():\n    assert shop.add(1, 2) == 3\n")
    ps.create_project("Shop", str(src))
    return "shop"


def add(project, **over):
    fields = dict(title="adds", source=PASSING, critical=False)
    return tc.add_test_case(project, **{**fields, **over})


def run_case(project, case_id, function="test_adds"):
    folder = code_reader.release_path("v1.0", project)
    tc.materialize_tests(project, folder)
    return run_tests(folder, [f"test_case_{case_id}.py::{function}"])


def test_add_and_list_and_delete(project):
    assert [add(project)["id"], add(project, title="again")["id"]] == [1, 2]
    assert [c["title"] for c in tc.list_test_cases(project)] == ["adds", "again"]
    tc.delete_test_case(project, 1)
    assert [c["id"] for c in tc.list_test_cases(project)] == [2]
    with pytest.raises(ProjectError) as err:
        tc.delete_test_case(project, 1)
    assert err.value.status == 404


@pytest.mark.parametrize("over", [
    {"title": ""}, {"title": "x" * 81}, {"source": "def test_x(:\n    pass\n"}, {"source": "x = 1\n"},
    {"source": "def helper():\n    pass\n"}, {"source": "# " + "x" * 205000},
])
def test_validation_rejects_bad_input(project, over):
    with pytest.raises(ProjectError) as err:
        add(project, **over)
    assert err.value.status == 400
    assert tc.list_test_cases(project) == []


def test_syntax_error_message_names_the_line(project):
    with pytest.raises(ProjectError) as err:
        add(project, source="import shop\n\ndef test_x(:\n    pass\n")
    assert "line 3" in str(err.value)


def test_added_python_test_passes_and_fails_correctly(project):
    good, bad = add(project), add(project, source=FAILING)
    assert run_case(project, good["id"])["passed"] == 1
    assert run_case(project, bad["id"])["failed"] == 1


def test_critical_checkbox_sets_marker(project):
    plain, critical = add(project, source=FAILING), add(project, source=FAILING, critical=True)
    assert run_case(project, plain["id"])["failed_critical"] == []
    assert run_case(project, critical["id"])["failed_critical"] == [f"test_case_{critical['id']}.py::test_adds"]


def test_several_test_functions_in_one_case_all_run(project):
    case = add(project, source=PASSING + "\n\ndef test_more():\n    assert shop.add(0, 0) == 0\n")
    folder = code_reader.release_path("v1.0", project)
    tc.materialize_tests(project, folder)
    ids = [f"test_case_{case['id']}.py::test_adds", f"test_case_{case['id']}.py::test_more"]
    assert run_tests(folder, ids)["passed"] == 2


def test_title_with_odd_characters_never_reaches_the_generated_code(project):
    title = 'He said "hi" \\ \n O\'Neil é; import os'
    case = add(project, title=title)
    text = tc.render_test(case)
    assert "O'Neil" not in text and "hi" not in text
    compile(text, "generated", "exec")
    assert tc.list_test_cases(project)[0]["title"] == title.strip()


def test_materialize_removes_deleted_cases(project):
    folder = code_reader.release_path("v1.0", project)
    one, two = add(project), add(project)
    assert tc.materialize_tests(project, folder) == 2
    tc.delete_test_case(project, one["id"])
    assert tc.materialize_tests(project, folder) == 1
    assert sorted(p.name for p in folder.glob("test_case_*.py")) == [f"test_case_{two['id']}.py"]


def test_protected_project_rejects_new_test_cases(project):
    path = code_reader.project_path(project) / "project.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "protected": True}))
    with pytest.raises(ProjectError) as err:
        add(project)
    assert err.value.status == 403
    assert tc.list_test_cases(project) == []


def test_update_changes_the_case_and_keeps_its_id(project):
    case = add(project)
    changed = tc.update_test_case(project, case["id"], "renamed", FAILING, True)
    assert changed["id"] == case["id"]
    saved = tc.list_test_cases(project)[0]
    assert (saved["title"], saved["source"], saved["critical"]) == ("renamed", FAILING, True)


def test_update_validates_and_finds_the_case(project):
    case = add(project)
    with pytest.raises(ProjectError) as err:
        tc.update_test_case(project, case["id"], "t", "def test_x(:\n", False)
    assert err.value.status == 400
    with pytest.raises(ProjectError) as err:
        tc.update_test_case(project, 99, "t", PASSING, False)
    assert err.value.status == 404
    assert tc.list_test_cases(project)[0]["title"] == "adds"


def test_list_all_tests_has_project_tests_and_added_cases(project):
    case = add(project, critical=True)
    tests = {t["id"]: t for t in tc.list_all_tests(project)}
    assert "test_shop.py::test_add" in tests and tests["test_shop.py::test_add"]["critical"] is False
    assert tests[f"test_case_{case['id']}.py::test_adds"]["critical"] is True


def test_read_test_file_returns_source(project):
    got = tc.read_test_file(project, "test_shop.py")
    assert "def test_add" in got["source"] and got["editable"] is True and got["version"] == "v1.0"


def test_save_test_file_changes_it_and_marks_results_stale(project):
    import time
    ps.save_result(project, "v1.0", {"decision": "DEPLOY", "risk_score": 1, "risk_level": "LOW", "retry_count": 0})
    time.sleep(0.05)
    tc.save_test_file(project, "test_shop.py", "import shop\n\ndef test_add():\n    assert shop.add(2, 2) == 4\n")
    assert "== 4" in tc.read_test_file(project, "test_shop.py")["source"]
    assert ps.list_versions(project)[0]["last_result"]["stale"] is True


def test_save_rejects_a_syntax_error_and_keeps_the_old_file(project):
    before = tc.read_test_file(project, "test_shop.py")["source"]
    with pytest.raises(ProjectError) as err:
        tc.save_test_file(project, "test_shop.py", "def test_x(:\n    pass\n")
    assert err.value.status == 400 and "line 1" in str(err.value)
    assert tc.read_test_file(project, "test_shop.py")["source"] == before


@pytest.mark.parametrize("name", ["../x.py", "conftest.py", "shop.py", "test_case_1.py", "test_missing.py", "test_a/b.py"])
def test_only_the_projects_own_test_files_can_be_opened(project, name):
    with pytest.raises(ProjectError) as err:
        tc.read_test_file(project, name)
    assert err.value.status in (400, 404)


def test_a_locked_file_can_be_viewed_but_not_saved(project):
    path = code_reader.project_path(project) / "project.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "locked_test_files": ["test_shop.py"]}))
    assert tc.read_test_file(project, "test_shop.py")["editable"] is False
    with pytest.raises(ProjectError) as err:
        tc.save_test_file(project, "test_shop.py", "def test_x():\n    pass\n")
    assert err.value.status == 403


def test_demo_shop_locks_only_the_files_with_the_planted_failures(monkeypatch):
    monkeypatch.undo()  # the real demo shop: nothing is written
    for locked in ("test_refund.py", "test_payment.py"):
        assert tc.read_test_file("demo-shop", locked)["editable"] is False
    got = tc.read_test_file("demo-shop", "test_refund.py")
    assert "def test_refund" in got["source"]
    with pytest.raises(ProjectError) as err:
        tc.save_test_file("demo-shop", "test_refund.py", got["source"])
    assert err.value.status == 403
    for open_file in ("test_auth.py", "test_checkout.py", "test_orders.py", "test_notification.py"):
        assert tc.read_test_file("demo-shop", open_file)["editable"] is True
