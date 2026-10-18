import pytest

import app


@pytest.fixture(scope="module")
def shared():
    return app.used_in_fixture()


@pytest.fixture
def broken_setup():
    app.used_by_error_tests(1)
    raise RuntimeError("setup boom")


@pytest.fixture
def broken_teardown():
    yield
    app.used_in_teardown()
    raise RuntimeError("teardown boom")


def test_ok(shared):
    assert app.used_by_target(1) == 4


def test_target(shared):
    assert app.used_by_target(2) == 7  # fails: 6


def test_unrelated():
    assert app.used_by_unrelated(5) == 0  # fails: 4


def test_unrelated_two():
    assert app.used_by_unrelated(1) == 9  # fails: 0


@pytest.mark.skip(reason="skipped")
def test_skip():
    app.used_by_skip(1)


@pytest.mark.xfail(reason="expected")
def test_xfail():
    assert app.used_by_xfail_tests(1) == 0


@pytest.mark.xfail(reason="nonstrict")
def test_xpass():
    assert app.used_by_xfail_tests(1) == 10


@pytest.mark.xfail(reason="strict", strict=True)
def test_xpass_strict():
    assert app.used_by_xfail_tests(2) == 20


@pytest.mark.xfail(reason="wants ValueError", raises=ValueError)
def test_xfail_raises_mismatch():
    app.used_by_xfail_tests(3)
    raise TypeError("other")


def test_imperative_xfail():
    app.used_by_xfail_tests(4)
    pytest.xfail("imperative")


def test_setup_error(broken_setup):
    app.used_by_error_tests(2)


def test_teardown_error(broken_teardown):
    app.used_by_error_tests(3)


@pytest.mark.parametrize("v", [0, 5], ids=["zero", "five[x]"])
def test_param(v):
    assert app.used_by_target(v) == (v + 1) * 2
