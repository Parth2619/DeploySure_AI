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
