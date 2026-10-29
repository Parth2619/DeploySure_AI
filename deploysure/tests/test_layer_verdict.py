from deploysure.tools.layer_verdict import layer_verdict


def scan(layers=None, contract=None, endpoints=None):
    return {"layers": layers or {}, "contract_issues": contract or [], "endpoint_changes": endpoints or []}


def api(name="POST /api/orders (sample 2)", verdict="regression", diffs=None, path="/api/orders", method="POST"):
    return {"name": name, "method": method, "path": path, "verdict": verdict, "differences": diffs or []}


def ui(name="Shopping flow", verdict="regression", diffs=None):
    return {"name": name, "verdict": verdict, "differences": diffs or []}


VALUE = [{"kind": "value_changed", "field": "total", "old": 2.5, "new": 1.25}]
PRICE_RENAMED = [{"kind": "field_removed", "field": "[0].price"}, {"kind": "field_added", "field": "[0].unit_price"}]
UNKNOWN = {"kind": "unknown_endpoint", "call": "GET /api/product", "file": "frontend/app.js"}
MISSING = {"kind": "missing_field", "endpoint": "GET /api/products", "field": "price", "read_by": ["frontend/app.js"]}


def test_a_clean_change_has_no_faulty_layer():
    v = layer_verdict(scan({"backend": ["backend/app.py"]}), [api(verdict="unchanged")], [ui(verdict="unchanged")])
    assert v["layers"] == [] and v["primary"] == "none" and v["confidence"] == "high"


def test_a_ui_text_change_and_a_new_field_are_not_faults():
    v = layer_verdict(scan({"frontend": ["frontend/app.js"]}), [api(verdict="benign_change")], [ui(verdict="ui_changed")])
    assert v["layers"] == []


def test_an_api_only_regression_is_the_backend():
    v = layer_verdict(scan({"backend": ["backend/app.py"]}), [api(diffs=VALUE)], [ui(verdict="ui_changed")])
    assert v["layers"] == ["backend"] and v["primary"] == "backend" and v["confidence"] == "medium"
    assert any("POST /api/orders (sample 2)" in r for r in v["reasons"])


def test_a_page_that_calls_a_missing_route_is_the_frontend():
    diffs = [{"kind": "new_failed_request", "request": "GET /api/product 404"}, {"kind": "items_lost", "field": "2:#products li"}]
    v = layer_verdict(scan({"frontend": ["frontend/app.js"]}, [UNKNOWN]), [api(verdict="unchanged")], [ui(diffs=diffs)])
    assert v["layers"] == ["frontend"] and v["confidence"] == "high"
    assert any("GET /api/product" in r for r in v["reasons"])


def test_a_renamed_field_that_the_page_still_reads_is_the_connection():
    v = layer_verdict(scan({"backend": ["backend/app.py"]}, [MISSING]), [api("GET /api/products", diffs=PRICE_RENAMED, path="/api/products", method="GET")],
                      [ui(diffs=[{"kind": "broken_value", "field": "3:#products li", "old": ["$4.50"], "new": ["$NaN"]}])])
    assert v["layers"] == ["connection"] and v["primary"] == "connection" and v["confidence"] == "high"
    assert any("price" in r for r in v["reasons"])


def test_a_route_the_backend_removed_is_the_connection_not_the_frontend():
    v = layer_verdict(scan({"backend": ["backend/app.py"]}, [UNKNOWN], [{"endpoint": "GET /api/product", "kind": "endpoint_removed", "fields": []}]), [], [])
    assert v["layers"] == ["connection"]


def test_a_missing_route_when_only_the_backend_changed_is_the_connection():
    assert layer_verdict(scan({"backend": ["backend/app.py"]}, [UNKNOWN]), [], [])["layers"] == ["connection"]


def test_two_unrelated_faults_name_both_layers():
    v = layer_verdict(scan({"backend": ["a.py"], "frontend": ["b.js"]}), [api(diffs=VALUE)],
                      [ui(diffs=[{"kind": "new_page_error", "detail": "TypeError: x"}])])
    assert v["layers"] == ["backend", "frontend"] and v["primary"] == "backend and frontend" and v["confidence"] == "medium"


def test_a_broken_page_after_a_backend_only_change_is_blamed_on_the_backend():
    failed = [{"kind": "status_changed", "old": 200, "new": 500}]
    page = [{"kind": "new_failed_request", "request": "POST /api/quote 500"}]
    v = layer_verdict(scan({"backend": ["backend/pricing.py"]}), [api("POST /api/quote (sample 2)", diffs=failed, path="/api/quote")], [ui(diffs=page)])
    assert v["layers"] == ["backend"] and v["confidence"] == "high" and v["evidence"] == {"static": 0, "api": 1, "browser": 1}


def test_a_new_version_that_does_not_start_is_blamed_on_what_changed():
    assert layer_verdict(scan({"backend": ["backend/app.py"]}), [], [], start_error="SyntaxError")["layers"] == ["backend"]
    only_deps = layer_verdict(scan({"dependencies": ["requirements.txt"]}), [], [], start_error="ModuleNotFoundError")
    assert only_deps["layers"] == ["environment"] and "did not start" in only_deps["reasons"][0]


def test_checks_that_cannot_be_trusted_lower_the_confidence():
    v = layer_verdict(scan(), [api(verdict="unreliable")], [ui(verdict="unreliable")])
    assert v["layers"] == [] and v["confidence"] == "low"
    assert layer_verdict(scan(), [api(verdict="unchanged")], [], browser_error="Playwright is not installed")["confidence"] == "medium"


def test_the_evidence_counts_are_reported():
    v = layer_verdict(scan({"backend": ["a.py"]}, [MISSING]), [api(diffs=PRICE_RENAMED, path="/api/products", method="GET")], [ui()])
    assert v["evidence"] == {"static": 1, "api": 1, "browser": 1}
