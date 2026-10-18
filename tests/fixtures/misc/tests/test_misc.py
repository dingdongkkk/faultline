import sys
import time

import pytest

import app


def test_passes():
    assert app.compute(1) == 4


def test_pure_fail():
    assert 1 + 1 == 3


@pytest.fixture
def broken():
    raise RuntimeError("setup")


def test_setup_fail(broken):
    assert app.compute(1) == 4


@pytest.mark.xfail(strict=True, reason="strict")
def test_strict_xpass():
    assert app.compute(1) == 4


def test_slow_under_observation():
    if "faultline_probe.observe_plugin" in sys.modules:
        time.sleep(60)
    assert app.compute(2) == 7


def test_lambda():
    assert app.triple(2) == 5
