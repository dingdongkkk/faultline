"""Group a user's events into sessions separated by inactivity gaps."""

from datetime import timedelta

GAP = timedelta(minutes=30)


def sessionize(events):
    ordered = sorted(events, key=lambda e: e["at"])
    sessions = []
    current = []
    for event in ordered:
        if current and event["at"] - current[-1]["at"] > GAP:
            sessions.append(current)
            current = []
        current.append(event)
    if current:
        sessions.append(current)
    return sessions
