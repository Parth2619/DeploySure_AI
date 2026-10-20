import pytest

import checkout

pytestmark = pytest.mark.critical


def test_coupon_applied():
    assert checkout.apply_coupon(100.0, "SAVE10") == 90.0


def test_unknown_coupon_ignored():
    assert checkout.apply_coupon(100.0, "FAKE") == 100.0


def test_checkout_charges_discounted_total():
    assert checkout.checkout(100.0, "tok_visa", "SAVE20")["amount"] == 80.0


def test_checkout_requires_card():
    with pytest.raises(ValueError):
        checkout.checkout(100.0, "")
