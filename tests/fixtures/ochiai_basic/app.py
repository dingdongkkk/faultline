X = 1  # import-time


def shared():
    return 5


def f(a):
    if a > 2:
        return a * 2
    return a + 1
