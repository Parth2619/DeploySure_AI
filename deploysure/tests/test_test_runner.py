import pytest

from deploysure.tools.code_reader import release_path
from deploysure.tools.test_runner import collect_tests, parse_collect, parse_junit, run_tests

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3">
<testcase classname="test_pay" name="test_ok"><properties><property name="critical" value="True"/></properties></testcase>
<testcase classname="test_pay" name="test_bad"><properties><property name="critical" value="True"/></properties><failure message="x"/></testcase>
<testcase classname="test_misc" name="test_skip"><skipped/></testcase>
</testsuite></testsuites>"""


def test_parse_collect_keeps_only_test_ids():
    out = "test_a.py::test_one\ntest_a.py::test_two\n\n2 tests collected in 0.01s\n"
    assert parse_collect(out) == ["test_a.py::test_one", "test_a.py::test_two"]


def test_parse_junit(tmp_path):
    f = tmp_path / "r.xml"
    f.write_text(JUNIT)
    r = parse_junit(f)
    assert [(x["id"], x["status"], x["critical"]) for x in r] == [
        ("test_pay.py::test_ok", "passed", True),
        ("test_pay.py::test_bad", "failed", True),
        ("test_misc.py::test_skip", "skipped", False),
    ]


def test_collect_finds_20_tests_and_11_critical():
    tests = collect_tests(release_path("v2.0"))
    assert len(tests) == 20 and sum(t["critical"] for t in tests) == 11


def test_v21_all_20_pass():
    r = run_tests(release_path("v2.1"))
    assert (r["total"], r["passed"], r["failed"], r["error"]) == (20, 20, 0, None)


def test_v22_has_exactly_the_planted_failures():
    r = run_tests(release_path("v2.2"))
    assert (r["total"], r["passed"], r["failed"]) == (20, 18, 2)
    assert sorted(r["failed_tests"]) == ["test_payment.py::test_refund_amount_is_full", "test_refund.py::test_refund"]
    assert sorted(r["failed_critical"]) == sorted(r["failed_tests"])


def test_run_only_selected_tests():
    r = run_tests(release_path("v2.0"), ["test_notification.py::test_shipping_notice"])
    assert r["total"] == 1 and r["passed"] == 1


def test_unknown_test_id_is_an_error_not_a_pass():
    r = run_tests(release_path("v2.0"), ["test_nope.py::test_missing"])
    assert r["error"] and r["total"] == 0


def test_timeout_is_reported(tmp_path):
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(10)\n")
    r = run_tests(tmp_path, timeout=1)
    assert r["error"].startswith("timeout")


def test_critical_by_module_name(tmp_path):
    (tmp_path / "pay.py").write_text("def f():\n    return 1\n")
    (tmp_path / "test_pay.py").write_text("import pay\n\ndef test_bad():\n    assert pay.f() == 2\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    assert run_tests(tmp_path, critical_modules={"pay"})["failed_critical"] == ["test_pay.py::test_bad"]
    assert run_tests(tmp_path)["failed_critical"] == []
    assert [t["critical"] for t in collect_tests(tmp_path, critical_modules={"pay"})] == [True]


def test_collection_error_is_raised_not_dropped(tmp_path):
    from deploysure.tools.test_runner import CollectionError
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "test_broken.py").write_text("import missing_module\n\ndef test_x():\n    assert True\n")
    with pytest.raises(CollectionError):
        collect_tests(tmp_path)


def test_marker_critical_counts_even_without_the_conftest_hook(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    critical: x\n")
    (tmp_path / "conftest.py").write_text("")
    (tmp_path / "test_a.py").write_text("import pytest\n\n@pytest.mark.critical\ndef test_bad():\n    assert False\n")
    ids = {t["id"] for t in collect_tests(tmp_path) if t["critical"]}
    assert ids == {"test_a.py::test_bad"}
    assert run_tests(tmp_path, critical_ids=ids)["failed_critical"] == ["test_a.py::test_bad"]
    assert run_tests(tmp_path)["failed_critical"] == []
