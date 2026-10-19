import json

import pytest

from deploysure.api import REPORT_KEYS, check_release, list_releases, run_release_validation, stream_release_validation

NODES = ["planner", "change_analysis", "impact_analysis", "test_selection", "test_execution",
         "risk_assessment", "decision", "critic"]


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("DEPLOYSURE_LLM", "mock")
    monkeypatch.setenv("DEMO_SEED_WRONG_DECISION", "1")


def test_stream_scenario_a_event_order_and_shape():
    events = list(stream_release_validation("v2.1"))
    assert [e["node"] for e in events] == NODES + ["final"]
    assert all(e["status"] == "done" and e["timestamp"] and "state_update" in e for e in events)
    json.dumps(events)  # the UI and SSE need every event to be JSON-safe


def test_stream_scenario_b_shows_the_retry_loop():
    nodes = [e["node"] for e in stream_release_validation("v2.2")]
    assert nodes == NODES + ["replan"] + NODES + ["final"]


def test_final_report_has_exactly_the_contract_keys():
    report = list(stream_release_validation("v2.1"))[-1]["final_report"]
    assert set(report) == set(REPORT_KEYS)
    assert len(report["trace"]) == len(NODES)


def test_run_release_validation_returns_final_report():
    r = run_release_validation("v2.2")
    assert (r["decision"], r["critic_result"], r["retry_count"], r["risk_score"]) == ("BLOCK", "PASS", 1, 87)
    assert any("DEMO_SEED_WRONG_DECISION" in line for line in r["trace"])


@pytest.mark.parametrize("bad", ["../x", "v9.9", "", "v2.1/../v2.2", "..", "v2 1"])
def test_bad_release_ids_are_rejected(bad):
    with pytest.raises((ValueError, FileNotFoundError)):
        check_release(bad)


def test_list_releases():
    assert [r["release_id"] for r in list_releases()] == ["v2.1", "v2.2"]
