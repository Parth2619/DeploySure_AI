"""Both demo scenarios through the real graph and real pytest runs. The AI is the test stub from conftest.py."""
import pytest

from deploysure.orchestration.graph import build_graph, initial_state
from deploysure.tools import code_reader, project_store, test_cases
from tests import fake_llm


@pytest.fixture(autouse=True)
def seed_on(monkeypatch):
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "1")


def run(release_id: str, project_id: str = "demo-shop") -> tuple[dict, list[str]]:
    """Returns the final state and every decision made along the way, in order."""
    state, decisions = dict(initial_state(release_id, project_id)), []
    for chunk in build_graph().stream(initial_state(release_id, project_id), stream_mode="updates", config={"recursion_limit": 60}):
        for node, update in chunk.items():
            state.update({k: v for k, v in update.items() if k != "trace"})
            state["trace"] = state["trace"] + update.get("trace", [])
            if node == "decision":
                decisions.append(update["decision"])
    return state, decisions


def test_scenario_a_safe_release_deploys():
    state, decisions = run("v2.1")
    assert state["changed_files"] == ["notification.py"]
    assert len(state["selected_tests"]) == 6
    assert len(state["all_test_ids"]) == 20 and set(state["selected_tests"]) <= set(state["all_test_ids"])
    assert state["test_results"]["failed"] == 0
    assert state["risk_score"] == 12 and state["risk_level"] == "LOW"
    assert decisions == ["DEPLOY"]
    assert state["decision"] == "DEPLOY" and state["critic_result"] == "PASS" and state["retry_count"] == 0


def test_scenario_b_critic_rejects_seeded_deploy_then_blocks():
    state, decisions = run("v2.2")
    assert state["changed_files"] == ["payment.py"]
    assert len(state["selected_tests"]) == 20
    assert (state["test_results"]["passed"], state["test_results"]["failed"]) == (18, 2)
    assert "test_refund.py::test_refund" in state["test_results"]["failed_critical"]
    assert state["risk_score"] == 87 and state["risk_level"] == "CRITICAL"
    assert decisions == ["DEPLOY", "BLOCK"]
    assert state["decision"] == "BLOCK" and state["critic_result"] == "PASS" and state["retry_count"] == 1
    assert any("critic: FAIL" in line for line in state["trace"])


def test_stubborn_wrong_model_ends_in_manual_review(monkeypatch):
    # A model that always says DEPLOY must hit the retry cap, never loop forever, never ship.
    real_answer = fake_llm.answer
    monkeypatch.setattr(fake_llm, "answer", lambda prompt, name: {"decision": "DEPLOY", "reason": "looks fine"}
                        if name == "Verdict" else real_answer(prompt, name))
    state, decisions = run("v2.2")
    assert decisions == ["DEPLOY", "DEPLOY", "DEPLOY"]
    assert state["retry_count"] == 2 and state["critic_result"] == "FAIL"
    assert state["decision"] == "HOLD" and "manual review" in state["decision_reason"].lower()


ADDS = "import shop\n\n\ndef test_adds():\n    assert shop.add(2, 3) == 5\n"


def write(folder, files: dict) -> None:
    folder.mkdir()
    for name, text in files.items():
        (folder / name).write_text(text)


def test_added_test_case_runs_and_a_critical_failure_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")
    good, broken = "def add(a, b):\n    return a + b\n", "def add(a, b):\n    return a - b\n"
    write(tmp_path / "v1", {"shop.py": good})
    write(tmp_path / "v2", {"shop.py": broken})
    project_store.create_project("Calc", str(tmp_path / "v1"))
    project_store.add_version("calc", "v2", str(tmp_path / "v2"), "oops")
    case = test_cases.add_test_case("calc", "adds numbers", ADDS, True)
    state, _ = run("v2", "calc")
    case_id = f"test_case_{case['id']}.py::test_adds"
    assert state["selected_tests"] == [case_id] and state["test_results"]["failed_critical"] == [case_id]
    assert state["decision"] == "BLOCK" and state["critic_result"] == "PASS"


def test_demo_seed_applies_only_to_the_demo_shop(monkeypatch, tmp_path):
    # A user's own project must never get the forced wrong first answer, even with the switch on.
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    good, broken = "def add(a, b):\n    return a + b\n", "def add(a, b):\n    return a - b\n"
    write(tmp_path / "v1", {"shop.py": good})
    write(tmp_path / "v2", {"shop.py": broken})
    project_store.create_project("Calc", str(tmp_path / "v1"))
    project_store.add_version("calc", "v2", str(tmp_path / "v2"), "oops")
    test_cases.add_test_case("calc", "adds", ADDS, True)
    state, decisions = run("v2", "calc")
    assert decisions == ["BLOCK"] and state["retry_count"] == 0


def test_change_with_no_covering_tests_holds(monkeypatch, tmp_path):
    # A changed module that no test imports must never pass as safe, and must not run the whole suite.
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")
    shop = "def add(a, b):\n    return a + b\n"
    test = "import shop\n\ndef test_add():\n    assert shop.add(1, 2) == 3\n"
    write(tmp_path / "v1", {"shop.py": shop, "other.py": "def sub(a, b):\n    return a - b\n", "test_shop.py": test})
    project_store.create_project("Tiny", str(tmp_path / "v1"))
    write(tmp_path / "v2", {"shop.py": shop, "other.py": "def sub(a, b):\n    return b - a\n", "test_shop.py": test})
    project_store.add_version("tiny", "v2", str(tmp_path / "v2"), "swap sub")
    state, decisions = run("v2", "tiny")
    assert state["changed_files"] == ["other.py"] and state["selected_tests"] == []
    assert "no tests" in state["test_results"]["error"]
    assert state["decision"] == "HOLD" and state["critic_result"] == "PASS"


def two_versions(tmp_path, name, v1: dict, v2: dict) -> str:
    write(tmp_path / "v1", v1)
    write(tmp_path / "v2", v2)
    pid = project_store.create_project(name, str(tmp_path / "v1"))["id"]
    project_store.add_version(pid, "v2", str(tmp_path / "v2"), "change")
    return pid


def test_broken_test_collection_never_deploys(monkeypatch, tmp_path):
    # v2 removes util.f, so test_util.py cannot even be imported. That must not look like a pass.
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")
    tests = {"test_util.py": "from util import f\n\ndef test_f():\n    assert f() == 1\n",
             "test_app.py": "import app\n\ndef test_g():\n    assert app.g() == 2\n", "app.py": "def g():\n    return 2\n"}
    pid = two_versions(tmp_path, "Broken", {"util.py": "def f():\n    return 1\n", **tests},
                       {"util.py": "def h():\n    return 1\n", **tests})
    state, _ = run("v2", pid)
    assert state["decision"] == "HOLD" and "collect" in state["test_results"]["error"]


def test_uncovered_changed_module_prevents_deploy(monkeypatch, tmp_path):
    # b.py changed and no test imports it, even though a.py is covered and passes.
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")
    test_a = {"test_a.py": "import a\n\ndef test_x():\n    assert a.f() == 1\n"}
    pid = two_versions(tmp_path, "Partial", {"a.py": "def f():\n    return 1\n", "b.py": "X = 1\n", **test_a},
                       {"a.py": "def f():\n    return 1  # tweak\n", "b.py": "X = 2\n", **test_a})
    state, _ = run("v2", pid)
    assert state["test_results"]["uncovered"] == ["b"] and state["decision"] == "HOLD"


def test_unchanged_version_runs_the_full_suite(monkeypatch, tmp_path):
    monkeypatch.setattr(code_reader, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "0")
    files = {"shop.py": "def add(a, b):\n    return a + b\n", "test_shop.py": "import shop\n\ndef test_add():\n    assert shop.add(1, 2) == 3\n"}
    pid = two_versions(tmp_path, "Same", files, files)
    state, _ = run("v2", pid)
    assert state["changed_files"] == [] and state["test_results"]["passed"] == 1 and state["decision"] == "DEPLOY"


def test_trace_says_why_the_ai_was_not_used(monkeypatch):
    from deploysure.models import llm

    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    state, _ = run("v2.1")
    ai_lines = [line for line in state["trace"] if "AI not used" in line]
    assert len(ai_lines) >= 4 and all("GROQ_API_KEY is not set" in line for line in ai_lines)
    assert state["decision"] == "DEPLOY"  # the deterministic parts still decide
