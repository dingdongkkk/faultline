"""Event filters."""

IGNORED_ACTIONS = {"heartbeat", "ping"}


def meaningful(events):
    return [e for e in events if e["action"] not in IGNORED_ACTIONS]


def for_user(events, user):
    return [e for e in events if e["user"] == user]
