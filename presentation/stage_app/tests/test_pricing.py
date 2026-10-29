import pytest

from backend.pricing import apply_discount


def test_ten_percent_discount():
    assert apply_discount(200.0, 10) == 180.0


def test_half_price():
    assert apply_discount(80.0, 50) == 40.0


def test_full_discount_is_free_not_negative():
    assert apply_discount(50.0, 100) == 0.0


def test_no_discount_keeps_the_price():
    assert apply_discount(100.0, 0) == 100.0


def test_negative_price_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(-1.0, 10)


def test_discount_above_100_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(100.0, 101)
