"""Read 'timestamp | user | action' lines into event dicts."""

from .timeparse import parse_timestamp


def read_events(lines):
    events = []
    for raw in lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        ts, user, action = (part.strip() for part in raw.split("|"))
        events.append({"at": parse_timestamp(ts), "user": user, "action": action})
    return events
