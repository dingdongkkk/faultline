"""Tiny checkout. Business rule: bulk discounts apply to orders of MORE than
the tier threshold (11+ items for the 10-item tier)."""

TIERS = {10: 10, 50: 20}  # threshold -> percent off
AUDIT = []


def bulk_rate(qty, tiers=TIERS):
    rate = 0
    for threshold in sorted(tiers):
        if qty >= threshold:
            rate = tiers[threshold]
    return rate


def line_total(qty, unit_cents):
    return qty * unit_cents


def apply_rate(total, rate):
    return total - total * rate // 100


def log_discount(rate):
    AUDIT.append(rate)


def checkout(items):
    total = 0
    qty = 0
    for q, unit in items:
        total += line_total(q, unit)
        qty += q
    rate = bulk_rate(qty)
    if rate:
        log_discount(rate)
    return apply_rate(total, rate)
