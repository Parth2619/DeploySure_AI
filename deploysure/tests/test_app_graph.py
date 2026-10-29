"""The app-mode workflow on the real TinyShop repo: real git, real apps, real browser. Only the AI is the test stub."""
from deploysure.models import llm
from deploysure.orchestration.app_graph import build_app_graph, initial_app_state
from deploysure.tools import api_checks, browser_checks, git_tool
from tests import fake_llm


def run(repo, old, new):
    """Returns the merged final state and the list of node names in the order they finished."""
    state, nodes = dict(initial_app_state(repo, old, new)), []
    for chunk in build_app_graph().stream(initial_app_state(repo, old, new), stream_mode="updates", config={"recursion_limit": 60}):
        for node, update in chunk.items():
            nodes.append(node)
            state.update({k: v for k, v in update.items() if k not in {"trace", "messages"}})
            state["trace"] = state["trace"] + update.get("trace", [])
            state["messages"] = state["messages"] + update.get("messages", [])
    return state, nodes


def test_a_safe_change_deploys(tinyshop):
    state, nodes = run(tinyshop[0], "v1.1", "v1.2")
    assert nodes == ["change_scan", "planner", "check_writing", "differential_run", "layer_attribution", "risk_assessment", "decision", "critic"]
    assert state["layer_verdict"]["primary"] == "none" and state["layer_verdict"]["confidence"] == "high"
    assert (state["risk_level"], state["decision"], state["critic_result"], state["retry_count"]) == ("LOW", "DEPLOY", "PASS", 0)
    assert state["api_report"]["summary"]["regressions"] == [] and state["browser_report"]["summary"]["regressions"] == []


def test_a_backend_bug_is_held_and_blamed_on_the_backend(tinyshop):
    state, _ = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert state["layer_verdict"]["layers"] == ["backend"] and state["layer_verdict"]["confidence"] == "medium"
    assert (state["risk_level"], state["decision"], state["critic_result"], state["retry_count"]) == ("MEDIUM", "HOLD", "PASS", 0)
    assert state["api_report"]["summary"]["regressions"]


def test_a_frontend_bug_is_blocked_and_blamed_on_the_frontend(tinyshop):
    state, _ = run(tinyshop[0], "v1.2", "v2.1-frontend-bug")
    assert state["layer_verdict"]["layers"] == ["frontend"] and state["layer_verdict"]["confidence"] == "high"
    assert (state["risk_score"], state["risk_level"], state["decision"], state["critic_result"]) == (73, "HIGH", "BLOCK", "PASS")
    assert state["api_report"]["summary"]["regressions"] == []


def test_a_contract_break_is_blocked_and_blamed_on_the_connection(tinyshop):
    state, _ = run(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert state["layer_verdict"]["layers"] == ["connection"] and state["layer_verdict"]["confidence"] == "high"
    assert any("price" in r for r in state["layer_verdict"]["reasons"])
    assert (state["risk_score"], state["risk_level"], state["decision"]) == (100, "CRITICAL", "BLOCK")


def test_the_critic_rejects_a_model_that_says_deploy_and_the_loop_ends_in_manual_review(tinyshop, monkeypatch):
    real_answer = fake_llm.answer
    monkeypatch.setattr(fake_llm, "answer", lambda prompt, name: {"decision": "DEPLOY", "reason": "looks fine"}
                        if name == "Verdict" else real_answer(prompt, name))
    state, nodes = run(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert state["critic_result"] == "FAIL" and state["retry_count"] == 2
    assert state["decision"] == "HOLD" and "manual review" in state["decision_reason"].lower()
    assert nodes.count("differential_run") == 1 and nodes.count("decision") == 3  # the evidence is gathered once, only the decision is retried
    challenges = [m for m in state["messages"] if m["kind"] == "challenge"]
    assert len(challenges) == 3 and all((m["from"], m["to"]) == ("critic", "decision") for m in challenges)  # the Critic challenges each wrong answer


def test_a_new_version_that_does_not_start_is_blocked(tinyshop, tmp_path):
    clone = tmp_path / "clone"
    git_tool.git_run(tinyshop[0].parent, "clone", "--quiet", str(tinyshop[0]), str(clone))
    (clone / "backend" / "app.py").write_text("def broken(:\n")
    git_tool.git_run(clone, "add", "-A")
    git_tool.git_run(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "break it")
    state, _ = run(clone, "v1.2", "HEAD")
    assert state["start_error"] and state["layer_verdict"]["layers"] == ["backend"]
    assert (state["risk_score"], state["risk_level"], state["decision"], state["critic_result"]) == (100, "CRITICAL", "BLOCK", "PASS")
    assert state["api_report"]["results"] == []


def test_a_baseline_that_does_not_start_cannot_be_compared_and_is_held(tinyshop, tmp_path):
    clone = tmp_path / "clone"
    git_tool.git_run(tinyshop[0].parent, "clone", "--quiet", str(tinyshop[0]), str(clone))
    (clone / "backend" / "app.py").write_text("def broken(:\n")
    git_tool.git_run(clone, "add", "-A")
    git_tool.git_run(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "break it")
    state, _ = run(clone, "HEAD", "v1.2")  # old is broken, new is fine
    assert state["decision"] == "HOLD" and "old version did not start" in state["browser_error"]


def test_without_a_browser_the_static_scan_and_api_checks_still_decide(tinyshop, monkeypatch):
    def no_browser(*args, **kwargs):
        raise browser_checks.BrowserUnavailable("Playwright is not installed")

    monkeypatch.setattr(browser_checks, "run_browser_checks", no_browser)
    state, _ = run(tinyshop[0], "v1.2", "v2.1-frontend-bug")
    assert "Playwright is not installed" in state["browser_error"] and state["browser_report"]["results"] == []
    assert state["decision"] == "BLOCK" and state["layer_verdict"]["layers"] == ["frontend"]  # the static scan alone sees the wrong route
    assert state["layer_verdict"]["confidence"] == "medium"


def test_without_the_ai_the_probes_and_rules_still_decide_and_the_trace_says_why(tinyshop, monkeypatch):
    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    state, _ = run(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert (state["decision"], state["layer_verdict"]["primary"], state["critic_result"]) == ("BLOCK", "connection", "PASS")
    ai_lines = [line for line in state["trace"] if "AI not used" in line]
    assert len(ai_lines) >= 3 and all("GROQ_API_KEY is not set" in line for line in ai_lines)


def test_the_agents_talk_to_each_other_through_the_shared_state(tinyshop):
    state, nodes = run(tinyshop[0], "v1.2", "v2.1-frontend-bug")
    talk = [(m["from"], m["to"], m["kind"]) for m in state["messages"]]
    assert talk == [("change_scan", "planner", "info"), ("planner", "check_writing", "focus"), ("check_writing", "differential_run", "info"),
                    ("differential_run", "layer_attribution", "info"), ("layer_attribution", "decision", "info"),
                    ("risk_assessment", "decision", "info"), ("decision", "critic", "info")]
    assert state["focus"] == ["api_contract", "page_behavior"] and state["check_round"] == 1 and nodes.count("check_writing") == 1
    prompts = {c["task"]: c["prompt"] for c in llm.call_log[-8:]}
    assert "PRIORITY (from the Planner)" in prompts["api_checks"] and "api_contract:" in prompts["api_checks"]  # the Planner's answer reached the Check writer
    assert "changed layers: frontend (1)" in prompts["planner"] and "contract issues between page and API: 1" in prompts["planner"]  # the scan reached the Planner
    assert "layer_attribution: The fault is in: frontend" in prompts["decision"] and "risk_assessment: Risk 73" in prompts["decision"]


def test_the_planners_choice_changes_what_the_check_writer_is_asked(tinyshop, monkeypatch):
    real_answer = fake_llm.answer
    monkeypatch.setattr(fake_llm, "answer", lambda prompt, name: {"focus": ["data_values"], "reason": "numbers changed"}
                        if name == "AppPlan" else real_answer(prompt, name))
    state, _ = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert state["focus"] == ["data_values"]
    api_prompt = next(c["prompt"] for c in reversed(llm.call_log) if c["task"] == "api_checks")
    assert "data_values: numbers the API calculates" in api_prompt and "api_contract:" not in api_prompt


def test_without_the_ai_the_planner_still_decides_by_fixed_rules(tinyshop, monkeypatch):
    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    state, _ = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert state["focus"] == ["api_contract", "data_values"] and "fixed rules" in state["focus_reason"]
    assert any("planner: focus api_contract, data_values (AI not used" in line for line in state["trace"])


def _make_first_api_check_unreliable(monkeypatch, every_time=False):
    """Marks the first API check unreliable, as if the old version had refused its input. Returns the list of runs."""
    real, runs = api_checks.run_checks, []

    def run_checks(old_url, new_url, checks):
        results = real(old_url, new_url, checks)
        runs.append(len(checks))
        if results and (every_time or len(runs) == 1):
            results[0] = {**results[0], "verdict": "unreliable"}
        return results

    monkeypatch.setattr(api_checks, "run_checks", run_checks)
    return runs


def test_unreliable_checks_are_sent_back_to_the_check_writer_once(tinyshop, monkeypatch):
    runs = _make_first_api_check_unreliable(monkeypatch)
    state, nodes = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert nodes == ["change_scan", "planner", "check_writing", "differential_run", "check_writing", "differential_run",
                     "layer_attribution", "risk_assessment", "decision", "critic"]
    assert len(runs) == 2 and state["check_round"] == 2
    repair = [m for m in state["messages"] if m["kind"] == "repair"]
    assert len(repair) == 1 and (repair[0]["from"], repair[0]["to"]) == ("differential_run", "check_writing") and "unreliable" in repair[0]["text"]
    second_prompt = [c["prompt"] for c in llm.call_log if c["task"] == "api_checks"][-1]
    assert "PROBLEM WITH YOUR PREVIOUS CHECKS (from the Differential run)" in second_prompt
    assert any("second round" in line for line in state["trace"]) and state["decision"] == "HOLD"


def test_the_repair_loop_stops_after_one_round_even_if_checks_stay_unreliable(tinyshop, monkeypatch):
    _make_first_api_check_unreliable(monkeypatch, every_time=True)
    state, nodes = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert nodes.count("check_writing") == 2 and nodes.count("differential_run") == 2 and state["check_round"] == 2
    assert len([m for m in state["messages"] if m["kind"] == "repair"]) == 1


def test_without_the_ai_there_is_nothing_to_repair_so_the_loop_does_not_run(tinyshop, monkeypatch):
    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    _make_first_api_check_unreliable(monkeypatch)
    state, nodes = run(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert nodes.count("check_writing") == 1 and not [m for m in state["messages"] if m["kind"] == "repair"]


def test_the_trace_tells_the_story(tinyshop):
    state, _ = run(tinyshop[0], "v1.2", "v2.2-contract-break")
    text = "\n".join(state["trace"])
    assert "change_scan:" in text and "check_writing:" in text and "differential_run:" in text and "layer_attribution: connection" in text
