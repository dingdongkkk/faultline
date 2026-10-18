import subprocess
import sys
import threading
import time

CALLS = []  # any entry here means a user-defined hook was invoked by the observer


class Hostile:
    def __repr__(self):
        CALLS.append("repr")
        raise RuntimeError("repr called")

    def __str__(self):
        CALLS.append("str")
        raise RuntimeError("str called")

    @property
    def boom(self):
        CALLS.append("property")
        raise RuntimeError("property called")

    def __iter__(self):
        CALLS.append("iter")
        raise RuntimeError("iter called")

    def __len__(self):
        CALLS.append("len")
        raise RuntimeError("len called")

    def __eq__(self, other):
        CALLS.append("eq")
        raise RuntimeError("eq called")

    def __hash__(self):
        return 1

    def __lt__(self, other):
        CALLS.append("lt")
        raise RuntimeError("lt called")

    def __getattr__(self, name):
        CALLS.append("getattr:" + name)
        raise AttributeError(name)


class MyDict(dict):
    def items(self):
        CALLS.append("mydict.items")
        raise RuntimeError

    def __iter__(self):
        CALLS.append("mydict.iter")
        raise RuntimeError


class Meta(type):
    def __getattribute__(cls, name):
        CALLS.append("meta:" + name)
        return super().__getattribute__(name)


class WithMeta(metaclass=Meta):
    pass


def mutate(items):
    total = 0
    items.append(99)  # @mark:append
    total = sum(items)  # @mark:sum
    return total


def hostile_holder(h, d, w):
    x = [h, d, w, {h}]
    return 4  # @mark:hostile


def catches(v):
    try:
        raise KeyError(v)
    except KeyError:
        pass
    return v


def propagates(v):
    raise ValueError(v)


def gen(n):
    for i in range(n):
        yield i


def secrets(password, data):
    blob = "ghp_" + "a" * 30
    note = "safe"
    return note  # @mark:secrets


def limits():
    nested = [[[[1]]]]
    big = list(range(100))
    s = "x" * 1000
    huge = 10**60
    cyc = []
    cyc.append(cyc)
    unordered = {3, 1, 2}
    return 0  # @mark:limits


def spin(n):
    t = 0
    for i in range(n):
        t += i  # @mark:spin
    return t


def bulk_rate(qty):
    if qty >= 10:  # @mark:bulk
        return 10
    return 0
