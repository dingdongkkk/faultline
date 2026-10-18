"""Parse event timestamps. Sources emit either 24-hour 'YYYY-MM-DD HH:MM' or
12-hour 'YYYY-MM-DD hh:MM AM/PM'."""

from datetime import datetime


def parse_24h(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def parse_12h(text):
    date_part, clock, ampm = text.split()
    hour, minute = (int(x) for x in clock.split(":"))
    if ampm.upper() == "PM" and hour != 12:
        hour += 12
    year, month, day = (int(x) for x in date_part.split("-"))
    return datetime(year, month, day, hour, minute)


def parse_timestamp(text):
    text = text.strip()
    if text.upper().endswith(("AM", "PM")):
        return parse_12h(text)
    return parse_24h(text)
