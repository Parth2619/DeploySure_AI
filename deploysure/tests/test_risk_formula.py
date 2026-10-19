import pytest

from deploysure.tools.risk_formula import calculate_risk, risk_level


def test_scenario_a_scores_12_low():
    r = calculate_risk(["notification"], dependents=1, lines_changed=2, failed_critical=0, failed_noncritical=0)
    assert r["score"] == 12 and r["level"] == "LOW"


def test_scenario_b_scores_87_critical():
    r = calculate_risk(["payment"], dependents=3, lines_changed=4, failed_critical=2, failed_noncritical=0)
    assert r["score"] == 87 and r["level"] == "CRITICAL"


@pytest.mark.parametrize("score,level", [(0, "LOW"), (30, "LOW"), (31, "MEDIUM"), (60, "MEDIUM"),
                                         (61, "HIGH"), (80, "HIGH"), (81, "CRITICAL"), (100, "CRITICAL")])
def test_level_boundaries(score, level):
    assert risk_level(score) == level


def test_components_respect_caps():
    r = calculate_risk(["payment", "checkout"], dependents=50, lines_changed=5000, failed_critical=9, failed_noncritical=9)
    c = r["components"]
    assert c["change_impact"] == 25 and c["failed_test_severity"] == 30 and c["failure_count"] == 5
    assert r["score"] <= 100


def test_noncritical_failure_is_scored_lower_than_critical():
    crit = calculate_risk(["orders"], 1, 2, 1, 0)["score"]
    non = calculate_risk(["orders"], 1, 2, 0, 1)["score"]
    assert non < crit


def test_unknown_module_scores_zero_for_customer_and_critical():
    c = calculate_risk(["mystery"], 0, 0, 0, 0)["components"]
    assert c["customer_facing"] == 0 and c["critical_component"] == 0
