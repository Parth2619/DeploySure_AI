import json

import pytest

from deploysure import app_api
from deploysure.app_api import APP_REPORT_KEYS, AppRequestError


def test_bad_requests_are_refused_before_anything_runs(tinyshop, tmp_path):
    repo = tinyshop[0]
    with pytest.raises(AppRequestError, match="does not exist"):
        app_api.check_app_request(tmp_path / "missing", "v1.1", "v1.2")
    with pytest.raises(AppRequestError, match="not a git repository"):
        app_api.check_app_request(tmp_path, "v1.1", "v1.2")
    with pytest.raises(AppRequestError, match="unknown ref"):
        app_api.check_app_request(repo, "v1.1", "nope")
    with pytest.raises(AppRequestError, match="invalid ref"):
        app_api.check_app_request(repo, "--upload-pack=x", "v1.2")
    with pytest.raises(AppRequestError, match="same commit"):
        app_api.check_app_request(repo, "v1.2", "main")


def test_the_stream_reports_each_node_then_a_final_report(tinyshop):
    events = list(app_api.stream_app_validation(tinyshop[0], "v1.2", "v2.2-contract-break"))
    assert [e["node"] for e in events] == ["change_scan", "planner", "check_writing", "differential_run", "layer_attribution",
                                          "risk_assessment", "decision", "critic", "final"]
    assert all(e["status"] == "done" and e["timestamp"] and "state_update" in e for e in events)
    json.dumps(events)  # everything the UI receives must be JSON-safe


def test_each_event_says_what_the_agent_received_asked_the_ai_and_took(tinyshop):
    events = {e["node"]: e for e in app_api.stream_app_validation(tinyshop[0], "v1.2", "v2.1-frontend-bug") if e["node"] != "final"}
    json.dumps(events)
    scan = events["change_scan"]["io"]
    assert scan["input"] == {"repo": str(tinyshop[0]), "old": "v1.2", "new": "v2.1-frontend-bug"} and scan["ai"] == []  # plain code, no AI
    # a value an earlier agent made is a reference, so the big scan is not copied into every step
    assert events["layer_attribution"]["io"]["input"]["scan"] == {"from": "change_scan"}
    assert events["critic"]["io"]["input"]["decision"] == {"from": "decision"}
    assert events["planner"]["io"]["input"] == {"old": "v1.2", "new": "v2.1-frontend-bug", "scan": {"from": "change_scan"}}
    assert events["check_writing"]["io"]["input"]["focus"] == {"from": "planner"}  # the Planner's output is the Check writer's input
    assert [m["from"] for m in events["check_writing"]["io"]["messages_in"]] == ["planner"]
    for node, tasks in {"planner": ["planner"], "check_writing": ["api_checks", "browser_checks"], "decision": ["decision"], "critic": ["critic"]}.items():
        calls = events[node]["io"]["ai"]
        assert [c["task"] for c in calls] == tasks and all(c["prompt"] and isinstance(c["answer"], dict) and c["fallback"] is False for c in calls)
    assert "faulty_layer: frontend" in events["decision"]["io"]["ai"][0]["prompt"]  # the real prompt the model got
    assert all(isinstance(e["io"]["seconds"], float) for e in events.values())


def test_the_big_maps_are_kept_out_of_the_events(tinyshop):
    scan_event = next(e for e in app_api.stream_app_validation(tinyshop[0], "v1.2", "v2.1-frontend-bug") if e["node"] == "change_scan")
    scan = scan_event["state_update"]["scan"]
    assert "old_map" not in scan and "new_map" not in scan and scan["layers"] == {"frontend": ["frontend/app.js"]}


def test_the_final_report_has_the_contract_keys_and_the_answer(tinyshop):
    report = app_api.run_app_validation(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert set(report) == set(APP_REPORT_KEYS)
    assert (report["decision"], report["critic_result"], report["risk_level"]) == ("BLOCK", "PASS", "CRITICAL")
    assert report["layer_verdict"]["primary"] == "connection" and report["layers_changed"] == {"backend": ["backend/app.py"], "tests": ["tests/test_api.py"]}
    assert report["contract_issues"][0]["field"] == "price" and report["api_summary"]["regressions"] == ["List products"]
    assert report["trace"] and report["check_sources"] == {"api": "ai+probes", "browser": "ai+smoke"}
