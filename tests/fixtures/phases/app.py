def used_by_target(x):
    y = x + 1
    return y * 2


def used_by_unrelated(x):
    return x - 1


def used_by_xfail_tests(x):
    return x * 10


def used_by_skip(x):
    return x


def used_in_fixture():
    return {"ready": True}


def used_in_teardown():
    return None


def used_by_error_tests(x):
    return x
