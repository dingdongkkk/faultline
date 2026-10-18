"""Sales tax by region, in basis points."""

RATES_BP = {"US": 800, "DE": 1900, "JP": 1000, "UK": 2000}


def tax_for(amount, region):
    bp = RATES_BP.get(region, 0)
    return (amount * bp + 5000) // 10000
