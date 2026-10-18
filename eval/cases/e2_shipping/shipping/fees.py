"""Shipping fees in cents. Express adds a flat EXPRESS_SURCHARGE to any order."""

BASE = {"domestic": 1500, "international": 4000}
PER_KG = 200
EXPRESS_SURCHARGE = 1500
AUDIT = []


def base_fee(region):
    if region == "international":
        customs = BASE["international"]
        return customs
    return BASE["domestic"]


def weight_fee(weight_kg):
    if weight_kg > 5:
        return int((weight_kg - 5) * PER_KG)
    return 0


def shipping_fee(weight_kg, region="domestic", express=False):
    fee = base_fee(region) + weight_fee(weight_kg)
    if express:
        fee = fee * 2
        AUDIT.append(("express", region))
    return fee
