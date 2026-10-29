"""Regression tests for the pricing module. A test whose name starts with test_critical_ guards revenue: if one fails, the release is blocked."""
import pytest

from demo_app.pricing import apply_discount, cart_total


# ---- critical: the money has to be right ----

def test_critical_ten_percent_discount():
    assert apply_discount(200.0, 10) == 180.0


def test_critical_half_price():
    assert apply_discount(80.0, 50) == 40.0


def test_critical_final_price_is_never_negative():
    assert apply_discount(50.0, 100) == 0.0


def test_critical_cart_total_applies_the_discount():
    assert cart_total([20.0, 30.0, 70.0], 10) == 108.0


# ---- normal ----

def test_no_discount_keeps_the_price():
    assert apply_discount(100.0, 0) == 100.0


def test_full_discount_on_a_round_price_is_free():
    assert apply_discount(100.0, 100) == 0.0


def test_discount_is_rounded_to_cents():
    assert apply_discount(19.99, 15) == 16.99


def test_empty_cart_costs_nothing():
    assert cart_total([], 10) == 0.0


def test_cart_without_discount_is_the_plain_sum():
    assert cart_total([10.0, 20.0]) == 30.0


def test_result_is_a_float():
    assert isinstance(apply_discount(100.0, 0), float)


def test_negative_price_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(-1.0, 10)


def test_discount_above_100_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(100.0, 101)


def test_negative_discount_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(100.0, -5)
