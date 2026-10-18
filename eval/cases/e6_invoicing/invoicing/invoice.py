"""Invoice assembly: subtotal -> coupon -> tax -> currency -> text."""

from .catalog import price_of
from .currency import to_minor
from .discounts import apply_coupon
from .formatting import money
from .tax import tax_for


def subtotal(order):
    return sum(price_of(line.sku) * line.qty for line in order.lines)


def total_usd_cents(order):
    discounted = apply_coupon(subtotal(order), order.coupon)
    return discounted + tax_for(discounted, order.region)


def render(order):
    total = to_minor(total_usd_cents(order), order.currency)
    return f"Total: {money(total, order.currency)}"
