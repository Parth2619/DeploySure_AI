import pytest

from deploysure.tools import api_checks, app_map

EPS = [{"method": "GET", "path": "/api/products"}, {"method": "POST", "path": "/api/orders"},
       {"method": "GET", "path": "/api/orders/{order_id}"}]


def resp(status=200, body=None, error=None):
    return {"status": status, "json": body, "text": "", "error": error}


# ---------- validation ----------

def test_validate_keeps_good_checks_and_says_why_it_dropped_the_rest():
    checks = [
        {"name": "list", "method": "GET", "path": "/api/products"},
        {"name": "order", "method": "POST", "path": "/api/orders", "json_body": {"items": []}},
        {"name": "one", "method": "GET", "path": "/api/orders/1"},
        {"name": "ghost", "method": "GET", "path": "/api/nope"},
        {"name": "wrong method", "method": "DELETE", "path": "/api/products"},
        {"name": "absolute", "method": "GET", "path": "http://evil.example/api/products"},
        {"name": "query", "method": "GET", "path": "/api/products?x=1"},
        {"name": "huge", "method": "POST", "path": "/api/orders", "json_body": {"x": "a" * 3000}},
        {"name": "weird", "method": "TRACE", "path": "/api/products"},
    ]
    kept, dropped = api_checks.validate_checks(checks, EPS)
    assert [c["name"] for c in kept] == ["list", "order", "one"]
    assert {d["name"] for d in dropped} == {"ghost", "wrong method", "absolute", "query", "huge", "weird"}
    assert all(d["why"] for d in dropped)


def test_validate_removes_duplicates_caps_the_count_and_tidies_names():
    same = {"method": "GET", "path": "/api/products"}
    kept, _ = api_checks.validate_checks([{"name": "a", **same}, {"name": "b", **same}], EPS)
    assert [c["name"] for c in kept] == ["a"]
    many = [{"name": f"n{i}", "method": "POST", "path": "/api/orders", "json_body": {"i": i}} for i in range(20)]
    assert len(api_checks.validate_checks(many, EPS)[0]) == api_checks.MAX_CHECKS
    kept, _ = api_checks.validate_checks([{"name": "  " + "x" * 200, **same}], EPS)
    assert len(kept[0]["name"]) == 80


def test_the_schema_the_ai_must_follow():
    checks = api_checks.ApiChecks.model_validate({"checks": [{"name": "a", "method": "GET", "path": "/x"}]})
    assert checks.checks[0].json_body is None and checks.checks[0].expect_json is None
    with pytest.raises(ValueError):
        api_checks.ApiChecks.model_validate({"checks": []})


# ---------- fallback without the AI ----------

def test_fallback_probes_read_endpoints_and_sample_bodies(tinyshop):
    endpoints = app_map.build_map(tinyshop[0], "v1.2")["endpoints"]
    checks = api_checks.fallback_checks(endpoints)
    assert [c["name"] for c in checks] == ["GET /api/health", "GET /api/products", "POST /api/orders (sample 1)", "POST /api/orders (sample 2)"]
    assert checks[3]["json_body"] == {"items": [{"product_id": 2, "quantity": 2}]}


# ---------- comparing two answers ----------

def test_a_changed_value_is_reported():
    assert api_checks.compare_responses(resp(body={"total": 10.25, "id": 1}), resp(body={"total": 5.75, "id": 1})) == [
        {"kind": "value_changed", "field": "total", "old": 10.25, "new": 5.75}]


def test_a_renamed_field_is_a_removal_and_an_addition():
    assert api_checks.compare_responses(resp(body=[{"price": 4.5}]), resp(body=[{"unit_price": 4.5}])) == [
        {"kind": "field_removed", "field": "[0].price"}, {"kind": "field_added", "field": "[0].unit_price"}]


def test_status_and_errors_are_reported():
    assert api_checks.compare_responses(resp(200, {}), resp(500, {})) == [{"kind": "status_changed", "old": 200, "new": 500}]
    assert api_checks.compare_responses(resp(), resp(error="connection refused"))[0]["kind"] == "app_error"
    assert api_checks.compare_responses(resp(body={"a": 1}), resp(body={"a": 1})) == []


def test_nested_lists_are_compared_item_by_item():
    old, new = resp(body={"items": [{"q": 1}, {"q": 2}]}), resp(body={"items": [{"q": 1}]})
    assert api_checks.compare_responses(old, new) == [{"kind": "field_removed", "field": "items[1].q"}]


def test_assertions_are_optional_and_check_status_and_a_subset_of_json():
    assert api_checks.evaluate({}, resp()) is None
    assert api_checks.evaluate({"expect_status": 200}, resp(200)) is True
    assert api_checks.evaluate({"expect_status": 400}, resp(200)) is False
    assert api_checks.evaluate({"expect_json": {"total": 2.5}}, resp(body={"total": 2.5, "id": 1})) is True
    assert api_checks.evaluate({"expect_json": {"total": 9}}, resp(body={"total": 2.5})) is False
    assert api_checks.evaluate({"expect_json": {"name": "Notebook"}}, resp(body=[{"name": "Notebook"}, {"name": "Pen"}])) is True  # first item of a list


# ---------- old against new, on the real apps ----------

def probe(repo, old, new, extra=()):
    endpoints = app_map.build_map(repo, old)["endpoints"]
    return api_checks.run_differential(repo, old, new, api_checks.fallback_checks(endpoints) + list(extra))


def verdicts(report):
    return {r["name"]: r["verdict"] for r in report["results"]}


def test_a_safe_change_is_not_a_regression_and_a_new_field_is_benign(tinyshop):
    report = probe(tinyshop[0], "v1.1", "v1.2")
    assert report["summary"]["regression"] == 0
    assert verdicts(report)["POST /api/orders (sample 1)"] == "benign_change"
    assert verdicts(report)["GET /api/products"] == "unchanged"


def test_the_backend_bug_shows_up_as_a_changed_total(tinyshop):
    report = probe(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert report["summary"]["regressions"] == ["POST /api/orders (sample 2)"]
    assert verdicts(report)["POST /api/orders (sample 1)"] == "unchanged"  # quantity 1 hides the bug
    bad = next(r for r in report["results"] if r["verdict"] == "regression")
    assert bad["differences"] == [{"kind": "value_changed", "field": "total", "old": 2.5, "new": 1.25}]


def test_the_contract_break_shows_up_as_a_removed_field(tinyshop):
    report = probe(tinyshop[0], "v1.2", "v2.2-contract-break")
    assert report["summary"]["regressions"] == ["GET /api/products"]
    bad = next(r for r in report["results"] if r["verdict"] == "regression")
    assert {"kind": "field_removed", "field": "[0].price"} in bad["differences"]


def test_the_frontend_bug_is_invisible_to_api_checks(tinyshop):
    assert probe(tinyshop[0], "v1.2", "v2.1-frontend-bug")["summary"]["regressions"] == []


def test_a_wrong_expectation_is_ignored_but_the_comparison_still_catches_the_bug(tinyshop):
    wrong = {"name": "wrong total", "method": "POST", "path": "/api/orders", "json_body": {"items": [{"product_id": 2, "quantity": 2}]},
             "expect_json": {"total": 999}}
    report = probe(tinyshop[0], "v1.2", "v2.0-backend-bug", [wrong])
    result = next(r for r in report["results"] if r["name"] == "wrong total")
    assert result["assertion"] == {"old": False, "new": False} and result["verdict"] == "regression"


def test_an_expectation_that_holds_on_old_and_fails_on_new_is_a_regression(tinyshop):
    right = {"name": "two pens", "method": "POST", "path": "/api/orders", "json_body": {"items": [{"product_id": 2, "quantity": 2}]},
             "expect_json": {"total": 2.5}}
    result = next(r for r in probe(tinyshop[0], "v1.2", "v2.0-backend-bug", [right])["results"] if r["name"] == "two pens")
    assert result["assertion"] == {"old": True, "new": False} and result["verdict"] == "regression"


def test_a_check_the_old_version_cannot_answer_is_unreliable(tinyshop):
    broken = {"name": "needs a field", "method": "POST", "path": "/api/orders", "json_body": {"nope": 1}}
    result = next(r for r in probe(tinyshop[0], "v1.2", "v1.2", [broken])["results"] if r["name"] == "needs a field")
    assert result["old"]["status"] == 422 and result["verdict"] == "unreliable"
