from datetime import datetime

from activity.filters import meaningful
from activity.metrics import summarize
from activity.timeparse import parse_timestamp


def test_parse_24h():
    assert parse_timestamp("2026-03-01 18:05") == datetime(2026, 3, 1, 18, 5)


def test_parse_12h_pm():
    assert parse_timestamp("2026-03-01 06:05 PM") == datetime(2026, 3, 1, 18, 5)


def test_filters_drop_heartbeats():
    events = [{"action": "ping"}, {"action": "click"}]
    assert meaningful(events) == [{"action": "click"}]


def test_summarize_empty():
    assert summarize([]) == {"sessions": 0, "avg_minutes": 0.0}
