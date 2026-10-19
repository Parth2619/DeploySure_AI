from deploysure.tools.code_reader import release_path
from deploysure.tools.dependency_analyzer import build_import_graph, impacted_modules, is_test_module


def test_real_graph_edges():
    g = build_import_graph(release_path("v2.0"))
    assert g["orders"] == {"payment", "notification"}
    assert g["checkout"] == {"payment"}
    assert g["refund"] == {"payment"}
    assert g["payment"] == set()


def test_payment_change_reaches_checkout_orders_refund():
    g = build_import_graph(release_path("v2.0"))
    impacted = impacted_modules(g, ["payment"])
    assert {"checkout", "orders", "refund", "test_payment"} <= set(impacted)
    assert "auth" not in impacted and "notification" not in impacted


def test_notification_change_reaches_only_orders():
    g = build_import_graph(release_path("v2.0"))
    source = [m for m in impacted_modules(g, ["notification"]) if not is_test_module(m)]
    assert source == ["notification", "orders"]


def test_transitive_dependents_are_found():
    graph = {"a": set(), "b": {"a"}, "c": {"b"}, "d": set()}
    assert impacted_modules(graph, ["a"]) == ["a", "b", "c"]


def test_import_cycle_terminates():
    graph = {"a": {"b"}, "b": {"a"}}
    assert impacted_modules(graph, ["a"]) == ["a", "b"]


def test_import_forms_are_all_detected(tmp_path):
    (tmp_path / "x.py").write_text("")
    (tmp_path / "y.py").write_text("import x\n")
    (tmp_path / "z.py").write_text("from x import thing\n")
    (tmp_path / "w.py").write_text("import os\nfrom . import x\n")
    g = build_import_graph(tmp_path)
    assert g["y"] == {"x"} and g["z"] == {"x"} and g["w"] == {"x"}
