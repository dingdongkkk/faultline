from appconfig.settings import configure, default_config


def test_configure_override():
    assert configure(currency="EUR")["currency"] == "EUR"


def test_configure_keeps_other_defaults():
    assert configure(retries=5)["locale"] == "en_US"


def test_default_currency():
    assert default_config()["currency"] == "USD"
