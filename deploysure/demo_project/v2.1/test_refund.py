import pytest

import refund

pytestmark = pytest.mark.critical


def test_refund():
    r = refund.refund_order(1, 100.0, set())
    assert r == {"status": "refunded", "amount": 100.0}


def test_refund_twice_blocked():
    done = set()
    refund.refund_order(1, 100.0, done)
    with pytest.raises(ValueError):
        refund.refund_order(1, 100.0, done)


def test_refund_unknown_order():
    with pytest.raises(ValueError):
        refund.refund_order(9, None, set())
