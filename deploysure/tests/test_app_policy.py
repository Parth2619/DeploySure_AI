import pytest

from deploysure.tools import app_policy

VALUE = [{"kind": "value_changed", "field": "total", "old": 2.5, "new": 1.25}]
REMOVED = [{"kind": "field_removed", "field": "[0].price"}, {"kind": "field_added", "field": "[0].unit_price"}]


def api(verdict="regression", diffs=None):
    return {"name": "a", "method": "GET", "path": "/x", "verdict": verdict, "differences": diffs or []}


def ui(verdict="regression", diffs=None):
    return {"name": "u", "verdict": verdict, "differences": diffs or []}


def scan(layers=None, contract=None, endpoints=None):
    return {"layers": layers or {}, "contract_issues": contract or [], "endpoint_changes": endpoints or []}


ISSUE = {"kind": "unknown_endpoint", "call": "GET /api/product", "file": "frontend/app.js"}
SAFE = scan({"config": [".env.example"], "backend": ["backend/app.py"]}, endpoints=[{"endpoint": "POST /api/orders", "kind": "fields_added", "fields": ["currency"]}])


def risk(s, a, u, **kw):
    return app_policy.app_risk(s, a, u, **kw)


# ---------- risk ----------

def test_a_safe_change_is_low_risk():
    r = risk(SAFE, [api("benign_change")], [ui("ui_changed")])
    assert (r["score"], r["level"]) == (8, "LOW") and r["components"]["change_impact"] == 8


def test_a_changed_value_is_medium_risk():
    r = risk(scan({"backend": ["backend/app.py"]}), [api(diffs=VALUE)], [])
    assert (r["score"], r["level"]) == (38, "MEDIUM")


def test_a_broken_page_is_high_risk():
    r = risk(scan({"frontend": ["frontend/app.js"]}, [ISSUE]), [api("unchanged")], [ui()])
    assert (r["score"], r["level"]) == (73, "HIGH")
    assert r["components"] == {"change_impact": 3, "contract_break": 30, "api_regression": 0, "ui_regression": 40, "not_verified": 0}


def test_a_broken_contract_is_critical_and_the_score_never_passes_100():
    r = risk(scan({"backend": ["a.py"], "tests": ["t.py"]}, [{"kind": "missing_field"}], [{"kind": "fields_removed"}, {"kind": "fields_added"}]),
             [api(diffs=REMOVED)], [ui()])
    assert (r["score"], r["level"]) == (100, "CRITICAL")


def test_a_version_that_does_not_start_is_critical():
    assert risk(scan({"backend": ["a.py"]}), [], [], start_error="boom")["level"] == "CRITICAL"


def test_checks_that_could_not_run_add_risk():
    assert risk(scan(), [api("unchanged")], [], browser_error="no browser")["components"]["not_verified"] == 10


# ---------- the floor ----------

@pytest.mark.parametrize("name,s,a,u,kw,minimum", [
    ("clean", SAFE, [api("benign_change")], [ui("unchanged")], {}, "DEPLOY"),
    ("value changed", scan({"backend": ["a.py"]}), [api(diffs=VALUE)], [], {}, "HOLD"),
    ("page broken", scan({"frontend": ["b.js"]}, [ISSUE]), [], [ui()], {}, "BLOCK"),
    ("contract broken", scan({"backend": ["a.py"]}, [ISSUE]), [], [], {}, "BLOCK"),
    ("field removed from the api", scan({"backend": ["a.py"]}), [api(diffs=REMOVED)], [], {}, "BLOCK"),
    ("status changed", scan({"backend": ["a.py"]}), [api(diffs=[{"kind": "status_changed", "old": 200, "new": 500}])], [], {}, "BLOCK"),
    ("does not start", scan({"backend": ["a.py"]}), [], [], {"start_error": "boom"}, "BLOCK"),
    ("browser missing", SAFE, [api("unchanged")], [], {"browser_error": "none"}, "HOLD"),
    ("every check unreliable", SAFE, [api("unreliable")], [ui("unreliable")], {}, "HOLD"),
    ("no checks at all", SAFE, [], [], {}, "HOLD"),
])
def test_the_minimum_decision(name, s, a, u, kw, minimum):
    got, rules = app_policy.minimum_app_decision(s, a, u, **kw)
    assert got == minimum and rules, name


def test_the_floor_names_the_rules_that_fired():
    _, rules = app_policy.minimum_app_decision(scan({"frontend": ["b.js"]}, [ISSUE]), [], [ui()])
    assert any("page" in r for r in rules) and any("agree" in r for r in rules)


def test_evidence_counts_for_the_decision_prompt():
    counts = app_policy.evidence_counts(scan({"frontend": ["b.js"]}, [ISSUE]), [api(diffs=VALUE), api("unreliable")], [ui()])
    assert counts == {"breaking": 2, "behavior_changes": 1, "unreliable": 1, "incomplete": False}
