import pytest

import payment

pytestmark = pytest.mark.critical


def test_validate_amount_rejects_zero():
    with pytest.raises(ValueError):
        payment.validate_amount(0)


def test_calculate_fee():
    assert payment.calculate_fee(100.0) == 2.0


def test_charge_returns_receipt():
    r = payment.charge(50.0, "tok_visa")
    assert r["status"] == "charged" and r["fee"] == 1.0


def test_refund_amount_is_full():
    assert payment.refund_amount(100.0) == 100.0
