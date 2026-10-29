"""Tests of the deployment pipeline itself. Every scenario runs on a temporary copy, so these tests pass
whichever version of demo_app/pricing.py is currently in the demo folder."""
import shutil
from pathlib import Path

from app import critic, deployment_gate, risk_scorer
from app.main import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "baseline" / "pricing.py"
BUGGY = ROOT / "bug_variants" / "pricing_buggy.py"


def workspace(tmp_path: Path, pricing: Path) -> Path:
    """A copy of the demo with the given pricing file in demo_app. The gate tests are left out to avoid recursion."""
    for folder in ("app", "demo_app", "baseline"):
        shutil.copytree(ROOT / folder, tmp_path / folder, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "tests").mkdir()
    shutil.copy(ROOT / "tests" / "test_pricing.py", tmp_path / "tests")
    shutil.copy(ROOT / "pytest.ini", tmp_path)
    shutil.copy(pricing, tmp_path / "demo_app" / "pricing.py")
    return tmp_path


def run(tmp_path: Path, pricing: Path) -> dict:
    return run_pipeline(workspace(tmp_path, pricing), out=lambda _line: None)


def evidence(passed=10, critical_failed=(), failed=(), problem="", modified=False):
    names = [f"test_ok_{i}" for i in range(passed)]
    all_failed = list(critical_failed) + list(failed)
    tests = {"passed": names, "failed": all_failed, "errors": [], "critical_failed": list(critical_failed), "messages": {},
             "total": len(names) + len(all_failed), "problem": problem}
    release = {"missing": [], "modified": modified}
    return release, tests, risk_scorer.score_risk(release, tests)


# ---- the two scenarios, end to end ----

def test_original_pricing_passes_and_deploys(tmp_path):
    result = run(tmp_path, BASELINE)
    assert result["tests"]["failed"] == [] and result["tests"]["total"] > 0
    assert (result["final"], result["critic"]["verdict"], result["exit_code"]) == ("DEPLOY", "APPROVED", 0)
    assert result["risk"]["level"] == "LOW"


def test_buggy_pricing_fails_regression_tests_and_is_blocked(tmp_path):
    result = run(tmp_path, BUGGY)
    assert result["tests"]["critical_failed"] and result["tests"]["errors"] == [] and result["tests"]["problem"] == ""
    assert (result["final"], result["critic"]["verdict"], result["exit_code"]) == ("BLOCK", "CONFIRMED", 1)
    assert result["risk"]["level"] in ("HIGH", "CRITICAL")


def test_both_scenarios_use_the_same_tests_and_rules(tmp_path):
    a, b = run(tmp_path / "a", BASELINE), run(tmp_path / "b", BUGGY)
    assert [t["file"] for t in a["selected"]] == [t["file"] for t in b["selected"]]
    assert (tmp_path / "a" / "tests" / "test_pricing.py").read_bytes() == (tmp_path / "b" / "tests" / "test_pricing.py").read_bytes()
    assert a["tests"]["total"] == b["tests"]["total"]  # same tests ran, only the code under test differs


def test_the_same_code_gives_the_same_result_every_time(tmp_path):
    first = run(tmp_path / "1", BUGGY)
    for n in (2, 3):
        again = run(tmp_path / str(n), BUGGY)
        assert (again["tests"]["failed"], again["risk"], again["final"]) == (first["tests"]["failed"], first["risk"], first["final"])


def test_recovery_restores_the_passing_state(tmp_path):
    root = workspace(tmp_path, BUGGY)
    assert run_pipeline(root, out=lambda _l: None)["final"] == "BLOCK"
    shutil.copy(root / "baseline" / "pricing.py", root / "demo_app" / "pricing.py")  # what the documented command does
    assert run_pipeline(root, out=lambda _l: None)["final"] == "DEPLOY"


def test_the_buggy_file_is_a_drop_in_replacement(tmp_path):
    import importlib.util
    import inspect

    def signatures(path):
        spec = importlib.util.spec_from_file_location("m_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {n: str(inspect.signature(f)) for n, f in inspect.getmembers(module, inspect.isfunction)}
    assert signatures(BASELINE) == signatures(BUGGY) and BASELINE.read_text() != BUGGY.read_text()


# ---- missing or broken evidence ----

def test_a_pricing_file_that_cannot_be_imported_is_hold_not_block(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def apply_discount(:\n")
    result = run(tmp_path / "w", broken)
    assert result["tests"]["problem"] and result["tests"]["failed"] == []
    assert (result["final"], result["exit_code"]) == ("HOLD", 2)


def test_missing_test_file_is_hold(tmp_path):
    root = workspace(tmp_path, BASELINE)
    (root / "tests" / "test_pricing.py").unlink()
    result = run_pipeline(root, out=lambda _l: None)
    assert result["final"] == "HOLD" and "not found" in result["tests"]["problem"]


def test_no_tests_executed_is_hold():
    release, tests, risk = evidence(passed=0, problem="no tests were executed")
    assert deployment_gate.decide(release, tests, risk)["decision"] == "HOLD"


def test_a_non_critical_failure_is_hold():
    release, tests, risk = evidence(failed=["test_rounding"])
    assert deployment_gate.decide(release, tests, risk)["decision"] == "HOLD"


# ---- the gate and the score ----

def test_a_critical_failure_blocks_even_when_the_score_is_low():
    release, tests, risk = evidence(passed=500, critical_failed=["test_critical_x"])
    forced_low = {**risk, "score": 5, "level": "LOW"}
    assert deployment_gate.decide(release, tests, forced_low)["decision"] == "BLOCK"


def test_a_healthy_release_deploys():
    release, tests, risk = evidence()
    assert (risk["score"], deployment_gate.decide(release, tests, risk)["decision"]) == (5, "DEPLOY")


def test_a_changed_but_passing_file_is_not_blocked_for_being_changed():
    release, tests, risk = evidence(modified=True)
    assert deployment_gate.decide(release, tests, risk)["decision"] == "DEPLOY"


def test_risk_score_grows_with_the_evidence_and_stays_within_100():
    scores = [evidence()[2]["score"], evidence(failed=["a"])[2]["score"], evidence(critical_failed=["test_critical_a"])[2]["score"],
              evidence(passed=1, critical_failed=[f"test_critical_{i}" for i in range(9)], failed=["x"] * 9, modified=True)[2]["score"]]
    assert scores == sorted(scores) and scores[0] < scores[1] < scores[2] and scores[-1] <= 100


# ---- the critic ----

def test_the_critic_rejects_deploy_when_a_critical_test_failed():
    release, tests, risk = evidence(critical_failed=["test_critical_x"])
    check = critic.validate("DEPLOY", release, tests, risk)
    assert check["verdict"] == "REJECTED" and check["required"] == "BLOCK" and check["findings"]


def test_the_critic_rejects_a_low_score_that_hides_a_critical_failure():
    release, tests, risk = evidence(passed=500, critical_failed=["test_critical_x"])
    check = critic.validate("BLOCK", release, tests, {**risk, "score": 5, "level": "LOW"})
    assert check["verdict"] == "REJECTED" and any("LOW" in f for f in check["findings"])


def test_the_critic_rejects_a_report_whose_counts_do_not_add_up():
    release, tests, risk = evidence()
    assert critic.validate("DEPLOY", release, {**tests, "total": 99}, risk)["verdict"] == "REJECTED"


def test_the_critic_confirms_a_correct_decision_and_allows_a_stricter_one():
    release, tests, risk = evidence(critical_failed=["test_critical_x"])
    assert critic.validate("BLOCK", release, tests, risk)["verdict"] == "CONFIRMED"
    release, tests, risk = evidence()
    assert critic.validate("DEPLOY", release, tests, risk)["verdict"] == "APPROVED"
    assert critic.validate("HOLD", release, tests, risk)["verdict"] == "CONFIRMED"


def test_a_decision_the_critic_rejects_is_replaced_in_the_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment_gate, "decide", lambda *_: {"decision": "DEPLOY", "reason": "forced wrong answer"})
    result = run(tmp_path, BUGGY)
    assert (result["valid"], result["final"], result["exit_code"]) == (False, "BLOCK", 3)
