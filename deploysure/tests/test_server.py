import asyncio
import json

import pytest

pytest.importorskip("fastapi")  # server.py is optional

from deploysure import server
from deploysure.tools import code_reader, project_store
from deploysure.tools.project_store import ProjectError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")


SOURCE = "import shop\n\n\ndef test_adds():\n    assert shop.add(1, 2) == 3\n"


def src(tmp_path, name, code="def add(a, b):\n    return a + b\n"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "shop.py").write_text(code)
    (folder / "test_shop.py").write_text("import shop\n\ndef test_add():\n    assert shop.add(1, 2) == 3\n")
    return str(folder)


def make_shop(tmp_path):
    server.new_project(server.NewProject(name="Shop", folder_path=src(tmp_path, "v1")))
    return "shop"


def events(response) -> list[dict]:
    async def collect():
        return [chunk async for chunk in response.body_iterator]
    return [json.loads(frame[6:]) for frame in asyncio.run(collect())]


def test_sse_frame_format():
    frame = server.sse({"node": "critic"})
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:]) == {"node": "critic"}


def test_create_project_then_list_cards(tmp_path):
    card = server.new_project(server.NewProject(name="Shop", folder_path=src(tmp_path, "v1"), critical_modules=["shop"]))
    assert card["id"] == "shop" and card["latest_version"] == "v1.0"
    assert [c["id"] for c in server.projects()] == ["shop"]


def test_add_version_then_get_project_shows_two_versions(tmp_path):
    pid = make_shop(tmp_path)
    server.new_version(pid, server.NewVersion(version="v2", folder_path=src(tmp_path, "v2"), notes="second"))
    got = server.project(pid)
    assert [v["version"] for v in got["versions"]] == ["v1.0", "v2"] and got["modules"] == ["shop"]


def test_duplicate_project_raises_409(tmp_path):
    make_shop(tmp_path)
    with pytest.raises(ProjectError) as err:
        server.new_project(server.NewProject(name="Shop", folder_path=src(tmp_path, "again")))
    assert err.value.status == 409


def test_unknown_project_is_404():
    with pytest.raises(ProjectError) as err:
        server.project("nope")
    assert err.value.status == 404


def test_add_and_delete_test_case_routes(tmp_path):
    pid = make_shop(tmp_path)
    case = server.new_test(pid, server.NewTest(title="adds", source=SOURCE))
    assert [c["id"] for c in server.tests_list(pid)] == [case["id"]]
    server.remove_test(pid, case["id"])
    assert server.tests_list(pid) == []


def test_error_handler_turns_project_error_into_json_status():
    response = server.handle_project_error(None, ProjectError("already there", 409))
    assert response.status_code == 409 and json.loads(response.body) == {"detail": "already there"}


def test_analyze_unknown_version_is_404_before_streaming(tmp_path):
    pid = make_shop(tmp_path)
    with pytest.raises(ProjectError) as err:
        server.analyze(pid, "v9")
    assert err.value.status == 404


def test_analyze_first_version_is_400(tmp_path):
    pid = make_shop(tmp_path)
    with pytest.raises(ProjectError) as err:
        server.analyze(pid, "v1.0")
    assert err.value.status == 400


def test_analyze_streams_and_saves_last_result(tmp_path):
    pid = make_shop(tmp_path)
    server.new_version(pid, server.NewVersion(version="v2", folder_path=src(tmp_path, "v2", "def add(a, b):\n    return b + a\n")))
    got = events(server.analyze(pid, "v2"))
    assert got[-1]["node"] == "final" and got[-1]["final_report"]["decision"] in ("DEPLOY", "HOLD", "BLOCK")
    saved = project_store.list_versions(pid)[-1]["last_result"]
    assert saved["decision"] == got[-1]["final_report"]["decision"]


def test_syntax_error_version_gives_error_event(tmp_path):
    pid = make_shop(tmp_path)
    server.new_version(pid, server.NewVersion(version="v2", folder_path=src(tmp_path, "v2", "def add(:\n")))
    got = events(server.analyze(pid, "v2"))
    assert got[-1]["node"] == "error" and got[-1]["state_update"]["error"]


def test_all_tests_and_edit_routes(tmp_path):
    pid = make_shop(tmp_path)
    case = server.new_test(pid, server.NewTest(title="adds", source=SOURCE))
    edited = server.edit_test(pid, case["id"], server.NewTest(title="adds again", source=SOURCE.replace("1, 2", "2, 2").replace("3", "4")))
    assert edited["title"] == "adds again" and "== 4" in server.tests_list(pid)[0]["source"]
    ids = [t["id"] for t in server.all_tests(pid)]
    assert "test_shop.py::test_add" in ids and f"test_case_{case['id']}.py::test_adds" in ids


def test_two_analyses_of_one_version_conflict(tmp_path):
    from deploysure.api import stream_release_validation
    pid = make_shop(tmp_path)
    server.new_version(pid, server.NewVersion(version="v2", folder_path=src(tmp_path, "v2", "def add(a, b):\n    return b + a\n")))
    first = stream_release_validation("v2", pid)
    next(first)
    with pytest.raises(ProjectError) as err:
        next(stream_release_validation("v2", pid))
    assert err.value.status == 409
    first.close()
    next(stream_release_validation("v2", pid))  # the lock was released


def test_analyze_needs_the_ui_header():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        server.require_ui_header(None)
    assert err.value.status_code == 403
    server.require_ui_header("1")


def test_test_file_routes(tmp_path):
    pid = make_shop(tmp_path)
    got = server.test_file(pid, "test_shop.py")
    assert got["editable"] is True
    server.edit_test_file(pid, "test_shop.py", server.NewSource(source="import shop\n\ndef test_add():\n    assert shop.add(1, 1) == 2\n"))
    assert "== 2" in server.test_file(pid, "test_shop.py")["source"]
