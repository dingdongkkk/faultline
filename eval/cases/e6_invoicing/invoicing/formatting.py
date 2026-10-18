"""Human-readable money strings."""

from .currency import minor_units

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "KRW": "₩"}


def money(minor, currency):
    places = minor_units(currency)
    symbol = SYMBOLS.get(currency, currency + " ")
    if places == 0:
        return f"{symbol}{minor:,}"
    return f"{symbol}{minor / 10 ** places:,.{places}f}"
