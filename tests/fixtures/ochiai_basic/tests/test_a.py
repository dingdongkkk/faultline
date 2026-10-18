import pytest

import app


@pytest.fixture(scope="module")
def res():
    return app.shared()


def test_one(res):
    assert app.f(1) == 2


def test_two(res):
    assert app.f(3) == 5  # fails: f(3) == 6


@pytest.mark.parametrize("v", [1, 3])
def test_p(v):
    assert app.f(v) > 0
