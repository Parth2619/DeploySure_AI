"""Order creation and confirmation."""
import notification
import payment


def create_order(order_id: int, items: list[tuple[str, float, int]]) -> dict:
    if not items:
        raise ValueError("order needs at least one item")
    return {"id": order_id, "items": items}


def order_total(order: dict) -> float:
    return round(sum(price * qty for _, price, qty in order["items"]), 2)


def confirm_order(order: dict, card_token: str) -> dict:
    total = order_total(order)
    receipt = payment.charge(total, card_token)
    message = notification.order_confirmation(order["id"], total)
    return {"receipt": receipt, "message": message}
