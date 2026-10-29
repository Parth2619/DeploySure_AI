import notification


def test_order_confirmation_mentions_order():
    msg = notification.order_confirmation(7, 12.5)
    assert "7" in msg and "confirmed" in msg and "12.50" in msg


def test_shipping_notice():
    assert "shipped" in notification.shipping_notice(7)


def test_subject_format():
    assert notification.format_subject("refund", 7) == "[Shop] Refund for order 7"
