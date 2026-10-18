_REGISTRY = {}


def register(name, value):
    _REGISTRY[name] = value


def lookup(name):
    value = _REGISTRY.get(name, "default")
    return value
