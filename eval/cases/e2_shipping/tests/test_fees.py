from shipping.fees import shipping_fee


def test_domestic_light():
    assert shipping_fee(1) == 1500


def test_domestic_heavy():
    assert shipping_fee(7) == 1900


def test_international_standard():
    assert shipping_fee(2, region="international") == 4000


def test_express_domestic():
    assert shipping_fee(2, express=True) == 3000


def test_express_international():
    assert shipping_fee(2, region="international", express=True) == 5500
