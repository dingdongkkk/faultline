"""Product catalog. Prices are USD cents."""

PRICES = {
    "pen": 250,
    "notebook": 1200,
    "backpack": 4500,
    "lamp": 3800,
    "mug": 900,
}


class UnknownProduct(KeyError):
    pass


def price_of(sku):
    try:
        return PRICES[sku]
    except KeyError:
        raise UnknownProduct(sku) from None
