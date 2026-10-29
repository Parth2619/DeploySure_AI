import pytest

from deploysure.agents import check_writer
from deploysure.models import llm
from deploysure.tools import api_checks, app_scan
from tests import fake_llm


def names(checks):
    return [c["name"] for c in checks]


def test_the_prompt_has_the_endpoints_the_change_and_the_diff(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v2.0-backend-bug")
    prompt = check_writer.build_prompt(tinyshop[0], scan)
    assert "POST /api/orders" in prompt and "order_total" in prompt and "backend/app.py" in prompt
    assert "-    return round(sum(prices[i.product_id] * i.quantity for i in items), 2)" in prompt
    assert "frontend" not in prompt.split("CHANGE")[1].split("DIFF")[0]  # only the layers that changed are listed


def test_the_prompt_stays_small_even_for_a_big_change(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.0", "v2.2-contract-break")  # frontend, backend, config and tests all differ
    assert len(check_writer.build_prompt(tinyshop[0], scan)) < check_writer.MAX_PROMPT_CHARS


def test_ai_checks_come_first_and_the_probes_fill_up(tinyshop):
    result = check_writer.write_checks(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert result["source"] == "ai+probes" and result["note"] == ""
    assert names(result["checks"])[:2] == ["Order with quantity 3", "List products"]
    assert "POST /api/orders (sample 2)" in names(result["checks"]) and "GET /api/health" in names(result["checks"])


def test_without_the_ai_the_probes_are_used_and_the_reason_is_given(tinyshop, monkeypatch):
    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    result = check_writer.write_checks(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert result["source"] == "probes" and "GROQ_API_KEY is not set" in result["note"]
    assert names(result["checks"]) == ["GET /api/health", "GET /api/products", "POST /api/orders (sample 1)", "POST /api/orders (sample 2)"]


def test_invented_endpoints_from_the_ai_are_dropped(tinyshop, monkeypatch):
    ghost = {"checks": [{"name": "ghost", "method": "GET", "path": "/api/secrets"},
                        {"name": "evil", "method": "GET", "path": "http://evil.example/x"}]}
    monkeypatch.setattr(fake_llm, "answer", lambda prompt, name: ghost if name == "ApiChecks" else {})
    result = check_writer.write_checks(tinyshop[0], "v1.2", "v2.0-backend-bug")
    assert {d["name"] for d in result["dropped"]} == {"ghost", "evil"}
    assert result["source"] == "probes" and "no usable check" in result["note"]
    assert "ghost" not in names(result["checks"])


@pytest.mark.parametrize("new,expected", [
    ("v2.0-backend-bug", {"Order with quantity 3", "POST /api/orders (sample 2)"}),
    ("v2.2-contract-break", {"List products"}),  # the identical GET /api/products probe is removed as a duplicate
])
def test_ai_checks_plus_probes_catch_what_the_api_can_show(tinyshop, new, expected):
    checks = check_writer.write_checks(tinyshop[0], "v1.2", new)["checks"]
    report = api_checks.run_differential(tinyshop[0], "v1.2", new, checks)
    assert expected <= set(report["summary"]["regressions"])


def test_a_good_commit_has_no_regressions_with_ai_checks(tinyshop):
    checks = check_writer.write_checks(tinyshop[0], "v1.1", "v1.2")["checks"]
    assert api_checks.run_differential(tinyshop[0], "v1.1", "v1.2", checks)["summary"]["regressions"] == []


# ---------- browser scenarios ----------

from deploysure.tools import browser_checks


def test_the_browser_prompt_lists_selectors_page_calls_and_the_page_diff(tinyshop):
    scan = app_scan.scan_change(tinyshop[0], "v1.2", "v2.1-frontend-bug")
    prompt = check_writer.build_browser_prompt(tinyshop[0], scan)
    assert "#place-order" in prompt and ".add" in prompt and "POST /api/orders" in prompt
    assert '+    const res = await fetch("/api/product");' in prompt
    assert len(prompt) < check_writer.MAX_PROMPT_CHARS


def test_ai_scenarios_come_first_and_the_smoke_check_follows(tinyshop):
    result = check_writer.write_browser_checks(tinyshop[0], app_scan.scan_change(tinyshop[0], "v1.2", "v2.1-frontend-bug"))
    assert result["source"] == "ai+smoke" and result["note"] == ""
    assert names(result["checks"]) == ["Shopping flow", "Open the page and press the first button"]


def test_without_the_ai_only_the_smoke_check_runs(tinyshop, monkeypatch):
    def no_key(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", no_key)
    result = check_writer.write_browser_checks(tinyshop[0], app_scan.scan_change(tinyshop[0], "v1.2", "v2.1-frontend-bug"))
    assert result["source"] == "smoke" and "GROQ_API_KEY is not set" in result["note"]
    assert names(result["checks"]) == ["Open the page and press the first button"]


def test_unsafe_scenarios_from_the_ai_are_dropped(tinyshop, monkeypatch):
    evil = {"checks": [{"name": "evil", "steps": [{"action": "goto", "value": "http://evil.example/"}]}]}
    monkeypatch.setattr(fake_llm, "answer", lambda prompt, name: evil if name == "BrowserChecks" else {})
    result = check_writer.write_browser_checks(tinyshop[0], app_scan.scan_change(tinyshop[0], "v1.2", "v2.1-frontend-bug"))
    assert [d["name"] for d in result["dropped"]] == ["evil"] and result["source"] == "smoke" and "no usable" in result["note"]


@pytest.mark.parametrize("new,catches", [("v2.1-frontend-bug", True), ("v2.2-contract-break", True), ("v1.2", False)])
def test_ai_scenarios_plus_smoke_in_a_real_browser(tinyshop, new, catches):
    old = "v1.1" if new == "v1.2" else "v1.2"
    scan = app_scan.scan_change(tinyshop[0], old, new)
    checks = check_writer.write_browser_checks(tinyshop[0], scan)["checks"]
    report = browser_checks.run_browser_differential(tinyshop[0], old, new, checks)
    assert bool(report["summary"]["regressions"]) is catches
