"""Cart checkout. Critical component."""
import payment

COUPONS = {"SAVE10": 0.10, "SAVE20": 0.20}


def apply_coupon(total: float, code: str | None) -> float:
    rate = COUPONS.get(code or "", 0.0)
    return round(total * (1 - rate), 2)


def checkout(total: float, card_token: str, coupon: str | None = None) -> dict:
    final = apply_coupon(total, coupon)
    return payment.charge(final, card_token)
