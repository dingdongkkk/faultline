import pytest

from billing.split import split_bill


def test_even():
    assert split_bill(900, 3) == [300, 300, 300]


def test_small_remainder():
    assert split_bill(1000, 3) == [334, 333, 333]


def test_six_people():
    assert split_bill(1000, 6) == [167, 167, 167, 167, 166, 166]


def test_invalid():
    with pytest.raises(ValueError):
        split_bill(100, 0)
