from invoicing.invoice import render
from invoicing.models import Line, Order


def test_invoice_usd():
    order = Order([Line("notebook", 2), Line("pen", 4)])
    assert render(order) == "Total: $36.72"


def test_invoice_eur_with_coupon():
    order = Order([Line("backpack", 1)], region="DE", currency="EUR", coupon="SAVE10")
    assert render(order) == "Total: €44.34"


def test_invoice_jpy():
    order = Order([Line("lamp", 2), Line("mug", 1)], region="JP", currency="JPY")
    assert render(order) == "Total: ¥14,118"
