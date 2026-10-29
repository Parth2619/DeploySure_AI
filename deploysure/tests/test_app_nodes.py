from deploysure.agents import check_writer
from deploysure.agents.app_nodes import MAX_CHECK_ROUNDS, default_focus, repair_requested, say
from deploysure.tools import app_scan


def scan(layers=None, contract=None, endpoints=None):
    return {"layers": layers or {}, "contract_issues": contract or [], "endpoint_changes": endpoints or []}


def test_the_default_focus_follows_what_changed():
    assert default_focus(scan({"frontend": ["a.js"]})) == ["page_behavior"]
    assert default_focus(scan({"backend": ["a.py"]})) == ["api_contract", "data_values"]
    assert default_focus(scan({"frontend": ["a.js"]}, contract=[{"kind": "unknown_endpoint"}])) == ["api_contract", "page_behavior"]
    assert default_focus(scan({"config": [".env.example"], "dependencies": ["requirements.txt"]})) == ["config_and_dependencies"]
    assert default_focus(scan({"tests": ["t.py"]})) == ["api_contract", "page_behavior"]  # nothing specific: look at both sides
    assert len(default_focus(scan({"frontend": ["a"], "backend": ["b"], "config": ["c"]}, contract=[{}]))) <= 4


def test_a_message_is_a_small_dict_with_who_to_whom():
    assert say("planner", "check_writing", "focus", "go", round=1) == {"from": "planner", "to": "check_writing", "kind": "focus", "text": "go", "round": 1}


def test_a_repair_is_requested_only_for_the_current_round_and_never_past_the_cap():
    asked = {"messages": [say("differential_run", "check_writing", "repair", "x", round=1)], "check_round": 1}
    assert repair_requested(asked) is True
    assert repair_requested({**asked, "check_round": 2}) is False  # the answer to round 1 was already used
    assert repair_requested({"messages": [say("differential_run", "layer_attribution", "info", "x")], "check_round": 1}) is False
    assert repair_requested({"messages": [], "check_round": 0}) is False
    assert MAX_CHECK_ROUNDS == 2


def test_the_planners_focus_and_the_repair_hint_reach_both_prompts(tinyshop):
    change = app_scan.scan_change(tinyshop[0], "v1.2", "v2.0-backend-bug")
    for build in (check_writer.build_prompt, check_writer.build_browser_prompt):
        plain = build(tinyshop[0], change)
        assert "PRIORITY" not in plain and "PROBLEM WITH" not in plain
        told = build(tinyshop[0], change, ["data_values", "api_contract"], "These checks were unreliable: List products")
        assert "PRIORITY (from the Planner):" in told and "- data_values: numbers the API calculates" in told
        assert "PROBLEM WITH YOUR PREVIOUS CHECKS (from the Differential run):\nThese checks were unreliable: List products" in told
        assert len(told) <= check_writer.MAX_PROMPT_CHARS
