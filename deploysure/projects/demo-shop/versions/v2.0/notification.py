"""Customer messages."""


def order_confirmation(order_id: int, total: float) -> str:
    return f"Order {order_id} confirmed. Total: ${total:.2f}"


def shipping_notice(order_id: int) -> str:
    return f"Order {order_id} has shipped."


def format_subject(kind: str, order_id: int) -> str:
    return f"[Shop] {kind.title()} for order {order_id}"
