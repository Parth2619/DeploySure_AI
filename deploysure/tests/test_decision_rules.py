import pytest

from deploysure.tools.risk_formula import decision_allowed, minimum_decision


@pytest.mark.parametrize("level,crit,non,err,expected", [
    ("LOW", 0, 0, False, "DEPLOY"),
    ("LOW", 1, 0, False, "BLOCK"),
    ("CRITICAL", 0, 0, False, "BLOCK"),
    ("HIGH", 0, 0, False, "HOLD"),
    ("MEDIUM", 0, 0, False, "HOLD"),
    ("LOW", 0, 1, False, "HOLD"),
    ("LOW", 0, 0, True, "HOLD"),
    ("HIGH", 1, 0, False, "BLOCK"),
])
def test_minimum_decision(level, crit, non, err, expected):
    assert minimum_decision(level, crit, non, err)[0] == expected


def test_rules_fired_are_listed():
    _, fired = minimum_decision("CRITICAL", 2, 0)
    assert len(fired) == 2


def test_decision_allowed_is_never_less_cautious_than_minimum():
    assert not decision_allowed("DEPLOY", "BLOCK")
    assert not decision_allowed("HOLD", "BLOCK")
    assert not decision_allowed("DEPLOY", "HOLD")
    assert decision_allowed("BLOCK", "HOLD")
    assert decision_allowed("BLOCK", "BLOCK")
    assert decision_allowed("DEPLOY", "DEPLOY")
