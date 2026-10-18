from registry import lookup, register


def test_a_register():
    register("mode", "fast")
    assert lookup("mode") == "fast"


def test_b_lookup_default():
    assert lookup("mode") == "default"  # fails only after test_a_register ran


def test_c_other_default():
    assert lookup("other") == "default"
