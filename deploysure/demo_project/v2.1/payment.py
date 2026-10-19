"""Card payments. Critical component: money moves here."""

FEE_RATE = 0.02


def validate_amount(amount: float) -> None:
    if amount <= 0:
        raise ValueError("amount must be positive")


def calculate_fee(amount: float) -> float:
    return round(amount * FEE_RATE, 2)


def charge(amount: float, card_token: str) -> dict:
    validate_amount(amount)
    if not card_token:
        raise ValueError("card token required")
    return {"status": "charged", "amount": amount, "fee": calculate_fee(amount)}


def refund_amount(amount: float) -> float:
    """Customers get back everything they paid, fee included."""
    return amount
