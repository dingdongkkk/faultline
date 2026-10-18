import pytest

from invoicing.catalog import UnknownProduct, price_of
from invoicing.currency import to_minor
from invoicing.discounts import apply_coupon
from invoicing.formatting import money
from invoicing.tax import tax_for


def test_price_lookup():
    assert price_of("mug") == 900
    with pytest.raises(UnknownProduct):
        price_of("rocket")


def test_coupons():
    assert apply_coupon(10000, "SAVE10") == 9000
    assert apply_coupon(300, "FLAT500") == 0
    assert apply_coupon(1000, "BOGUS") == 1000


def test_tax_rounding():
    assert tax_for(1000, "US") == 80
    assert tax_for(1001, "DE") == 190


def test_to_minor_two_decimals():
    assert to_minor(10000, "EUR") == 9200
    assert to_minor(10000, "USD") == 10000


def test_money_two_decimals():
    assert money(123456, "EUR") == "€1,234.56"
