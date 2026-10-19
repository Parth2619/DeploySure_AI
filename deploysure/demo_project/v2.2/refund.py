"""Refunds. Critical component."""
import payment


def refund_order(order_id: int, order_total: float | None, refunded: set[int]) -> dict:
    if order_total is None:
        raise ValueError("unknown order")
    if order_id in refunded:
        raise ValueError("order already refunded")
    refunded.add(order_id)
    return {"status": "refunded", "amount": payment.refund_amount(order_total)}
