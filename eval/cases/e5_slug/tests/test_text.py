from names.text import display_name, slug


def test_display_name_spacing():
    assert display_name("  ada   lovelace ") == "Ada Lovelace"


def test_slug_basic():
    assert slug("Ada Lovelace") == "ada-lovelace"


def test_slug_strips_punctuation():
    assert slug("Hello, World!") == "hello-world"
