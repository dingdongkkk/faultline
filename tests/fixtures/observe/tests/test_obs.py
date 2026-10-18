import os
import subprocess
import sys
import threading
import time

import pytest

import app


def test_mutate():
    assert app.mutate([1, 2]) == 102


def test_hostile():
    h, d, w = app.Hostile(), app.MyDict(a=1), app.WithMeta()
    app.CALLS.clear()
    app.hostile_holder(h, d, w)
    assert app.CALLS == []


def test_exits():
    assert app.catches(1) == 1
    with pytest.raises(ValueError):
        app.propagates(2)
    assert list(app.gen(2)) == [0, 1]


def test_secrets():
    app.secrets("hunter2", {"api_key": "k", "ok": 1})


def test_limits():
    app.limits()


def test_spin_small():
    app.spin(50)


def test_spin_big():
    app.spin(300000)


def test_bulk_target():
    assert app.bulk_rate(10) == 0  # fails at the same place every time


def test_bulk_passing():
    assert app.bulk_rate(12) == 10


def test_sleeper():
    marker = os.environ.get("FL_TEST_PIDFILE")
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    if marker:
        with open(marker, "w") as f:
            f.write(str(p.pid))
    time.sleep(60)


def test_thread_and_subprocess():
    t = threading.Thread(target=time.sleep, args=(0.3,))
    t.start()
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    app.bulk_rate(1)
    t.join()


def test_flaky_message():
    assert app.bulk_rate(10) == int(os.environ.get("FL_EXPECT", "0"))
