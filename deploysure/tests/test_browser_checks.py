import pytest

from deploysure.tools import browser_checks as bc

SHOPPING = {"name": "shopping flow", "steps": [
    {"action": "goto", "value": "/"}, {"action": "wait", "value": "500"}, {"action": "read", "selector": "#products li"},
    {"action": "click", "selector": "button.add"}, {"action": "click", "selector": "button.add"}, {"action": "wait", "value": "200"},
    {"action": "read", "selector": "#total"}, {"action": "click", "selector": "#place-order"}, {"action": "wait", "value": "500"},
    {"action": "read", "selector": "#result"}]}


def obs(reads=None, requests=None, page_errors=None, step_error=None):
    return {"reads": reads or {}, "requests": requests or [], "page_errors": page_errors or [], "step_error": step_error}


# ---------- validation ----------

def test_validate_keeps_good_scenarios_and_prepends_a_goto():
    kept, dropped = bc.validate_browser_checks([SHOPPING, {"name": "no goto", "steps": [{"action": "read", "selector": "h1"}]}])
    assert [c["name"] for c in kept] == ["shopping flow", "no goto"] and dropped == []
    assert kept[1]["steps"][0] == {"action": "goto", "value": "/"}


@pytest.mark.parametrize("step,why", [
    ({"action": "goto", "value": "http://evil.example/"}, "path"),
    ({"action": "goto", "value": "//evil.example"}, "path"),
    ({"action": "evaluate", "value": "alert(1)"}, "unsupported action"),
    ({"action": "click"}, "selector"),
    ({"action": "read", "selector": "x" * 200}, "selector"),
    ({"action": "fill", "selector": "#a", "value": "v" * 200}, "value"),
    ({"action": "wait", "value": "99999"}, "wait"),
    ({"action": "wait", "value": "soon"}, "wait"),
])
def test_validate_drops_scenarios_with_unsafe_or_broken_steps(step, why):
    kept, dropped = bc.validate_browser_checks([{"name": "bad", "steps": [{"action": "goto", "value": "/"}, step]}])
    assert kept == [] and why in dropped[0]["why"]


def test_validate_caps_steps_and_scenarios():
    long = {"name": "long", "steps": [{"action": "goto", "value": "/"}] + [{"action": "wait", "value": "1"}] * 20}
    assert bc.validate_browser_checks([long])[1][0]["why"].startswith("more than")
    many = [{"name": f"s{i}", "steps": [{"action": "read", "selector": f"#a{i}"}]} for i in range(20)]
    assert len(bc.validate_browser_checks(many)[0]) == bc.MAX_BROWSER_CHECKS


def test_the_schema_the_ai_must_follow():
    ok = bc.BrowserChecks.model_validate({"checks": [{"name": "a", "steps": [{"action": "goto", "value": "/"}]}]})
    assert ok.checks[0].steps[0].selector is None
    with pytest.raises(ValueError):
        bc.BrowserChecks.model_validate({"checks": [{"name": "a", "steps": [{"action": "hack"}]}]})


def test_the_smoke_scenario_needs_no_ai():
    [smoke] = bc.smoke_checks()
    assert smoke["steps"][0] == {"action": "goto", "value": "/"} and any(s["action"] == "read" for s in smoke["steps"])
    assert bc.validate_browser_checks([smoke])[1] == []


# ---------- comparing what two runs saw ----------

def test_identical_runs_have_no_differences():
    one = obs({"1:#a": ["x"]}, ["GET /api/p 200"])
    assert bc.compare_observations(one, one) == []


def test_a_new_failing_request_is_reported_and_a_missing_one_too():
    old = obs(requests=["GET /api/products 200"])
    new = obs(requests=["GET /api/product 404"])
    assert bc.compare_observations(old, new) == [{"kind": "new_failed_request", "request": "GET /api/product 404"},
                                                  {"kind": "request_missing", "request": "GET /api/products 200"}]


def test_a_request_that_already_failed_on_the_old_version_is_not_new():
    both = obs(requests=["GET /x 500"])
    assert bc.compare_observations(both, both) == []


def test_broken_values_lost_items_and_plain_text_changes_are_told_apart():
    old = obs({"1:#list": ["Notebook $4.50", "Pen $1.25"], "2:#t": ["$9.00"], "3:#b": ["Add"]})
    new = obs({"1:#list": ["Notebook $NaN"], "2:#t": ["$4.50"], "3:#b": ["Add to cart"]})
    kinds = {d["field"]: d["kind"] for d in bc.compare_observations(old, new)}
    assert kinds == {"1:#list": "broken_value", "2:#t": "text_changed", "3:#b": "text_changed"}
    assert bc.compare_observations(obs({"1:#l": ["a", "b"]}), obs({"1:#l": []}))[0]["kind"] == "items_lost"


def test_page_errors_and_failed_steps_are_reported():
    diffs = bc.compare_observations(obs(), obs(page_errors=["TypeError: x"], step_error="step 3 (click #go): TimeoutError"))
    assert {d["kind"] for d in diffs} == {"step_failed", "new_page_error"}


def test_the_verdict_follows_the_kinds():
    assert bc.verdict(obs(), [{"kind": "text_changed"}]) == "ui_changed"
    assert bc.verdict(obs(), [{"kind": "broken_value"}]) == "regression"
    assert bc.verdict(obs(), []) == "unchanged"
    assert bc.verdict(obs(step_error="boom"), [{"kind": "text_changed"}]) == "unreliable"
    assert bc.verdict(obs(requests=["GET /x 500"]), []) == "unreliable"


# ---------- a real browser on the real apps ----------

def run(repo, old, new, checks):
    return bc.run_browser_differential(repo, old, new, checks)


def by_name(report):
    return {r["name"]: r for r in report["results"]}


def test_a_copy_change_is_ui_changed_not_a_regression(tinyshop):
    report = run(tinyshop[0], "v1.0", "v1.1", [SHOPPING])
    result = by_name(report)["shopping flow"]
    assert result["verdict"] == "ui_changed" and report["summary"]["regressions"] == []
    assert [d["kind"] for d in result["differences"]] == ["text_changed"]


def test_a_new_api_field_changes_nothing_in_the_page(tinyshop):
    assert run(tinyshop[0], "v1.1", "v1.2", [SHOPPING])["summary"]["regressions"] == []


def test_the_frontend_bug_shows_a_failed_request_and_an_empty_list(tinyshop):
    result = by_name(run(tinyshop[0], "v1.2", "v2.1-frontend-bug", [SHOPPING]))["shopping flow"]
    kinds = {d["kind"] for d in result["differences"]}
    assert result["verdict"] == "regression" and {"new_failed_request", "items_lost"} <= kinds
    assert {"kind": "new_failed_request", "request": "GET /api/product 404"} in result["differences"]


def test_the_contract_break_shows_nan_prices(tinyshop):
    result = by_name(run(tinyshop[0], "v1.2", "v2.2-contract-break", [SHOPPING]))["shopping flow"]
    assert result["verdict"] == "regression"
    assert any(d["kind"] == "broken_value" and "NaN" in str(d["new"]) for d in result["differences"])


def test_the_backend_bug_is_visible_in_the_page_as_a_different_total(tinyshop):
    result = by_name(run(tinyshop[0], "v1.2", "v2.0-backend-bug", [SHOPPING]))["shopping flow"]
    changed = [d for d in result["differences"] if d["kind"] == "text_changed"]
    assert result["verdict"] == "ui_changed" and changed[0]["old"] == ["Order #1 total $9.00"] and changed[0]["new"] == ["Order #1 total $4.50"]


def test_the_smoke_scenario_alone_catches_the_frontend_bug_and_the_contract_break(tinyshop):
    smoke = bc.smoke_checks()
    for new in ("v2.1-frontend-bug", "v2.2-contract-break"):
        assert run(tinyshop[0], "v1.2", new, smoke)["summary"]["regression"] == 1
    assert run(tinyshop[0], "v1.1", "v1.2", smoke)["summary"]["regressions"] == []


def test_a_selector_that_does_not_exist_on_the_old_version_makes_the_check_unreliable(tinyshop):
    ghost = {"name": "ghost", "steps": [{"action": "goto", "value": "/"}, {"action": "click", "selector": "#nope"}]}
    result = by_name(run(tinyshop[0], "v1.2", "v1.2", [ghost]))["ghost"]
    assert result["verdict"] == "unreliable" and "step 2" in result["old"]["step_error"]


def test_without_playwright_the_error_says_how_to_install_it(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(bc.BrowserUnavailable) as err:
        bc.run_browser_checks("http://127.0.0.1:1", "http://127.0.0.1:2", [SHOPPING])
    assert "pip install playwright" in str(err.value)
