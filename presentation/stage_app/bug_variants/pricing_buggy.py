"""Pricing rules for a fictional online store."""

MAX_DISCOUNT_PERCENT = 100


def apply_discount(price: float, discount_percent: float) -> float:
    """Final price after a percentage discount."""
    if price < 0:
        raise ValueError("price cannot be negative")
    if discount_percent < 0 or discount_percent > MAX_DISCOUNT_PERCENT:
        raise ValueError("discount must be between 0 and 100 percent")
    # Regression: the percentage is no longer divided by 100, so 10 percent off takes the price down by a factor of 10.
    return round(price * (1 - discount_percent), 2)
