import pytest

import orders


def test_order_total():
    o = orders.create_order(1, [("pen", 2.5, 4), ("book", 10.0, 1)])
    assert orders.order_total(o) == 20.0


def test_empty_order_rejected():
    with pytest.raises(ValueError):
        orders.create_order(2, [])


def test_confirm_order_charges_and_notifies():
    o = orders.create_order(42, [("pen", 5.0, 2)])
    r = orders.confirm_order(o, "tok_visa")
    assert r["receipt"]["amount"] == 10.0 and "42" in r["message"]
