"""Per-user activity report."""

from .filters import for_user, meaningful
from .metrics import summarize
from .reader import read_events
from .sessions import sessionize


def user_report(lines, user):
    events = for_user(meaningful(read_events(lines)), user)
    return summarize(sessionize(events))
