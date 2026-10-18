from money import to_cents


def test_whole():
    assert to_cents(1.5) == 150


def test_small():
    assert to_cents(0.29) == 29
