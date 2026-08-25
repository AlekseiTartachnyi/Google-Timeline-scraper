"""Names for the files a scrape writes.

Months and weekdays come from a table, not from `strftime('%b')`: the exported
names are English only, and the C library's month name follows whatever
regional setting the laptop happens to carry.
"""

from datetime import date as date_type
from datetime import datetime

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
# date.weekday() is 0 for Monday.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_PREFIX = "timeline_"


def month(day: date_type) -> str:
    """Return the three-letter English month, e.g. 'Aug'."""
    return _MONTHS[day.month - 1]


def weekday(day: date_type) -> str:
    """Return the three-letter English weekday, e.g. 'Thu'."""
    return _WEEKDAYS[day.weekday()]


def stamp_date(day: date_type) -> str:
    """Return a date as '2026-Aug-20'."""
    return f"{day.year}-{month(day)}-{day.day:02d}"


def header_date(day: date_type) -> str:
    """Return a date as the report's header reads it: '2026, Aug, 20, Thu'."""
    return f"{day.year}, {month(day)}, {day.day:02d}, {weekday(day)}"


def draft_stem(day: date_type, collected_at: datetime) -> str:
    """Return the file stem for one scraped day, e.g.
    'timeline_2026-Aug-20_15-30'.

    The collection time is part of the name because a day is scraped more than
    once — Google keeps revising a day for a while after it happens — and an
    earlier draft must not be overwritten by a later one.
    """
    return f"{_PREFIX}{stamp_date(day)}_{collected_at:%H-%M}"


def range_stem(first: date_type, last: date_type) -> str:
    """Return the file stem for a finished range, e.g.
    'timeline_2026-Aug-20 - 2026-Aug-24'.

    No collection time here: a range file is the settled result, one per range,
    and a second run of the same range replaces it rather than piling up.
    """
    return f"{_PREFIX}{stamp_date(first)} - {stamp_date(last)}"
