import pytest

from shop.cart import apply_rate, checkout


def test_small_order():
    assert checkout([(2, 100)]) == 200


@pytest.mark.parametrize("qty, expected", [(10, 1000), (12, 1080)])
def test_bulk_threshold(qty, expected):
    assert checkout([(qty, 100)]) == expected


def test_big_order():
    assert checkout([(30, 100), (30, 100)]) == 4800


def test_apply_rate_zero():
    assert apply_rate(1000, 0) == 1000
