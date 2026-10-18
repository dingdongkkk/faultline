"""Application settings with per-call overrides."""

DEFAULTS = {"currency": "USD", "locale": "en_US", "retries": 3}


def configure(**overrides):
    config = DEFAULTS
    config.update(overrides)
    return config


def default_config():
    return dict(DEFAULTS)
