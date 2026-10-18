"""Conversion from USD cents into a currency's minor units.

Most currencies have 2 decimal places; zero-decimal currencies (JPY, KRW)
are expressed in whole units.
"""

USD_RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 151.0, "KRW": 1380.0}
ZERO_DECIMAL = {"JPY", "KRW"}


def minor_units(currency):
    """Number of decimal places for the currency."""
    return 0 if currency.lower() in ZERO_DECIMAL else 2


def to_minor(usd_cents, currency):
    """Convert USD cents to the target currency's minor units (rounded)."""
    rate = USD_RATES[currency]
    major = usd_cents / 100 * rate
    places = minor_units(currency)
    return round(major * 10 ** places)
