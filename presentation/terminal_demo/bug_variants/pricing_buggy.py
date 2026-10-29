"""Pricing rules for a fictional online store: discounts and cart totals.

Release candidate with a "simplified" discount formula (the planted regression for the demo).
"""

MAX_DISCOUNT_PERCENT = 100


def apply_discount(price: float, discount_percent: float) -> float:
    """Final price after a discount."""
    if price < 0:
        raise ValueError("price cannot be negative")
    if discount_percent < 0 or discount_percent > MAX_DISCOUNT_PERCENT:
        raise ValueError("discount must be between 0 and 100 percent")
    # Regression: the percentage is subtracted as a flat amount, and the result is no longer kept at zero or above.
    return round(price - discount_percent, 2)


def cart_total(prices: list[float], discount_percent: float = 0) -> float:
    """Sum of the item prices with one discount applied to the whole cart."""
    return apply_discount(sum(prices), discount_percent)
