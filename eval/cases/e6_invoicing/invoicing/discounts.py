"""Coupons applied to the pre-tax subtotal (USD cents)."""

COUPONS = {
    "SAVE10": ("percent", 10),
    "FLAT500": ("flat", 500),
}


def apply_coupon(subtotal, coupon):
    if not coupon:
        return subtotal
    kind, value = COUPONS.get(coupon, (None, 0))
    if kind == "percent":
        return subtotal - subtotal * value // 100
    if kind == "flat":
        return max(0, subtotal - value)
    return subtotal
