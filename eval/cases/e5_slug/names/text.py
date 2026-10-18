"""Name helpers. Display names keep apostrophes and hyphens; slugs are URL-safe."""


def normalize_name(s):
    return " ".join(s.split())


def display_name(s):
    return normalize_name(s).title()


def slug(s):
    return normalize_name(s).lower().replace(" ", "-")
